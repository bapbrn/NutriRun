"""
NutriRun — Module RAG

1. Chargement des documents (markdown + PDF)
2. Découpage en chunks (RecursiveCharacterTextSplitter)
3. Vectorisation et indexation (FAISS + all-MiniLM-L6-v2)
4. Recherche par similarité cosinus

Ce RAG contient le savoir que l'on veut apporter au LLM pour créer un programme alimentaire en fonction des besoins calculés par calculator.py: recettes, timing nutritionnel, conseils d'hydratation, stratégies de course etc. 
"""

import os
import glob
import json
import hashlib
from langchain_community.document_loaders import TextLoader, PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS

os.environ["USE_TF"] = "false"
os.environ["USE_TORCH"] = "true"
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"


# 1. CHARGEMENT DES DOCUMENTS

def load_knowledge_base(knowledge_dir: str = "knowledge_base") -> list:
    """Charge tous les .md et .pdf du dossier knowledge_base."""
    documents = []

    # Fichiers markdown
    md_files = sorted(glob.glob(os.path.join(knowledge_dir, "*.md")))
    for file_path in md_files:
        loader = TextLoader(file_path, encoding="utf-8")
        docs = loader.load()
        for doc in docs:
            doc.metadata["source"] = os.path.basename(file_path)
        documents.extend(docs)

    # Fichiers PDF
    pdf_files = sorted(glob.glob(os.path.join(knowledge_dir, "*.pdf")))
    for file_path in pdf_files:
        loader = PyPDFLoader(file_path=file_path)
        docs = loader.load()
        for doc in docs:
            doc.metadata["source"] = os.path.basename(file_path)
        documents.extend(docs)

    total_files = len(md_files) + len(pdf_files)
    if total_files == 0:
        raise FileNotFoundError(
            f"Aucun fichier .md ou .pdf trouvé dans '{knowledge_dir}'.\n"
            f"Vérifie que le dossier knowledge_base/ contient les fichiers."
        )

    print(f"  {len(documents)} document(s) chargé(s) "
          f"({len(md_files)} .md, {len(pdf_files)} .pdf)")
    return documents



# 2. DÉCOUPAGE EN CHUNKS


def create_chunks(
    documents: list,
    chunk_size: int = 500,
    chunk_overlap: int = 100,
) -> list:
    """
    Découpe les documents en chunks avec RecursiveCharacterTextSplitter.
    On coupe en priorité aux titres markdown, puis paragraphes, puis phrases.
    Les chunks < 50 caractères sont filtrés (bruit).
    """
    text_splitter = RecursiveCharacterTextSplitter(
        separators=["\n## ", "\n### ", "\n\n", "\n", ". ", " "],
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        length_function=len,
        is_separator_regex=False,
    )

    chunks = text_splitter.split_documents(documents)

    # Filtrer les chunks trop courts
    chunks = [c for c in chunks if len(c.page_content.strip()) >= 50]

    print(f"  {len(chunks)} chunks créés "
          f"(taille: {chunk_size}, overlap: {chunk_overlap})")
    return chunks



# 3. CONSTRUCTION DU VECTOR STORE FAISS


def build_vectorstore(
    chunks: list,
    embedding_model_name: str = "all-MiniLM-L6-v2",
) -> tuple:
    embedding_model = HuggingFaceEmbeddings(model_name=embedding_model_name)
    vectordb = FAISS.from_documents(chunks, embedding_model)

    print(f"  Vector store construit : {len(chunks)} vecteurs "
          f"(modèle: {embedding_model_name})")
    return vectordb, embedding_model


# 4. CRÉATION DU RETRIEVER


def create_retriever(vectordb, k: int = 5):
    return vectordb.as_retriever(search_kwargs={"k": k})



# 5. FONCTION DE FORMATAGE DES DOCUMENTS POUR PROMPTING


def format_docs(docs: list) -> str:
    """Formate les docs récupérés pour les injecter dans le prompt (avec la source)."""
    formatted = []
    for doc in docs:
        source = doc.metadata.get("source", "inconnu")
        content = doc.page_content.strip()
        formatted.append(f"[Source: {source}]\n{content}")
    return "\n\n---\n\n".join(formatted)


def search_with_scores(vectordb, query: str, k: int = 5) -> list:
    """Recherche avec scores — utile pour debug."""
    results = vectordb.similarity_search_with_score(query, k=k)
    for doc, score in results:
        source = doc.metadata.get("source", "?")
        preview = doc.page_content[:120].replace("\n", " ")
        print(f"  [{score:.4f}] {source} — {preview}...")
    return results



# 6. FINGERPRINT DE LA KNOWLEDGE BASE


def _compute_kb_fingerprint(knowledge_dir: str) -> str:
    """Hash des noms + dates de modif des fichiers. Si ça change, on rebuild l'index."""
    files = sorted(
        glob.glob(os.path.join(knowledge_dir, "*.md"))
        + glob.glob(os.path.join(knowledge_dir, "*.pdf"))
    )
    fingerprint_data = []
    for f in files:
        fingerprint_data.append(f"{os.path.basename(f)}:{os.path.getmtime(f)}")
    raw = "|".join(fingerprint_data)
    return hashlib.md5(raw.encode()).hexdigest()



# 7. FONCTION D'INITIALISATION COMPLÈTE DU RAG


def init_rag(
    knowledge_dir: str = "knowledge_base",
    chunk_size: int = 500,
    chunk_overlap: int = 100,
    embedding_model_name: str = "all-MiniLM-L6-v2",
    n_docs: int = 5,
    index_dir: str = "faiss_index",
) -> tuple:
    """
    Initialise tout le pipeline RAG.
    Si l'index FAISS existe et que la KB n'a pas changé → chargement rapide.
    Sinon → rebuild complet et sauvegarde sur disque.
    """
    print("=" * 50)
    print("Initialisation du RAG")
    print("=" * 50)

    fingerprint_file = os.path.join(index_dir, "kb_fingerprint.json")
    current_fingerprint = _compute_kb_fingerprint(knowledge_dir)

    # Vérifier si un index FAISS valide existe
    saved_fingerprint = None
    if os.path.exists(fingerprint_file):
        with open(fingerprint_file, "r") as f:
            saved = json.load(f)
            saved_fingerprint = saved.get("fingerprint")

    embedding_model = HuggingFaceEmbeddings(model_name=embedding_model_name)

    if saved_fingerprint == current_fingerprint and os.path.exists(os.path.join(index_dir, "index.faiss")):
        print("  Index FAISS trouvé sur disque (knowledge base inchangée)")
        vectordb = FAISS.load_local(index_dir, embedding_model, allow_dangerous_deserialization=True)
        retriever = create_retriever(vectordb, k=n_docs)
        print(f"  Retriever prêt (k={n_docs})")
        print("=" * 50)
        return vectordb, retriever, []

    # Sinon, reconstruire l'index
    print("  Reconstruction de l'index FAISS...")
    documents = load_knowledge_base(knowledge_dir)
    chunks = create_chunks(documents, chunk_size, chunk_overlap)
    vectordb, _ = build_vectorstore(chunks, embedding_model_name)
    retriever = create_retriever(vectordb, k=n_docs)

    # Sauvegarder l'index et le fingerprint
    os.makedirs(index_dir, exist_ok=True)
    vectordb.save_local(index_dir)
    with open(fingerprint_file, "w") as f:
        json.dump({"fingerprint": current_fingerprint}, f)
    print(f"  Index sauvegardé dans {index_dir}/")

    print(f"  Retriever prêt (k={n_docs})")
    print("=" * 50)

    return vectordb, retriever, chunks

#####