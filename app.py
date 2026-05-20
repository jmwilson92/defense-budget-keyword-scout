#!/usr/bin/env python3
import os
import re
import json
import shutil
import tempfile
import streamlit as st
import fitz
from whoosh import index as whoosh_index
from whoosh.fields import Schema, TEXT, ID, STORED, KEYWORD
from whoosh.analysis import StemmingAnalyzer
from whoosh.qparser import MultifieldParser

APP_NAME = "DoD Budget Justification Keyword Scout"
INDEX_PATH = "./whoosh_index"

def clean_text(t):
    t = re.sub(r'[ \t]+', ' ', t)
    t = re.sub(r'\n{3,}', '\n\n', t)
    for x in [r'\bUNCLASSIFIED\b', r'THIS PAGE INTENTIONALLY LEFT BLANK']:
        t = re.sub(x, '', t, flags=re.IGNORECASE)
    return t.strip()

def extract_pe(text):
    m = re.search(r'PE\s+(\d{7}[A-Z]?)', text, re.IGNORECASE)
    return m.group(1).upper() if m else None

def process_pdf(path):
    docs = []
    try:
        doc = fitz.open(path)
    except:
        return docs
    
    src = os.path.basename(path)
    current_pe = "General"
    current_title = src.replace(".pdf", "")
    text_parts = []
    pages = []
    
    for i, page in enumerate(doc):
        txt = clean_text(page.get_text("text"))
        if len(txt) < 100:  # Lowered threshold
            continue
        new_pe = extract_pe(txt)
        if new_pe and new_pe != current_pe:
            if text_parts:
                docs.append({
                    "id": f"{src}_{pages[0]}_{pages[-1]}",
                    "pe_number": current_pe,
                    "program_title": current_title,
                    "source": src,
                    "pages": f"{pages[0]}-{pages[-1]}",
                    "content": "\n\n".join(text_parts)
                })
            current_pe = new_pe
            current_title = txt.split('\n')[0][:70]
            text_parts = [txt]
            pages = [i+1]
        else:
            text_parts.append(txt)
            pages.append(i+1)
    
    if text_parts:
        docs.append({
            "id": f"{src}_{pages[0]}_{pages[-1]}",
            "pe_number": current_pe,
            "program_title": current_title,
            "source": src,
            "pages": f"{pages[0]}-{pages[-1]}",
            "content": "\n\n".join(text_parts)
        })
    doc.close()
    return docs

def get_or_create_index():
    schema = Schema(
        id=ID(unique=True, stored=True),
        pe_number=KEYWORD(stored=True),
        program_title=TEXT(stored=True),
        source=TEXT(stored=True),
        pages=STORED(),
        content=TEXT(stored=True, analyzer=StemmingAnalyzer())
    )
    if not os.path.exists(INDEX_PATH):
        os.makedirs(INDEX_PATH)
        return whoosh_index.create_in(INDEX_PATH, schema)
    try:
        return whoosh_index.open_dir(INDEX_PATH)
    except:
        shutil.rmtree(INDEX_PATH)
        os.makedirs(INDEX_PATH)
        return whoosh_index.create_in(INDEX_PATH, schema)

def add_to_index(ix, docs):
    writer = ix.writer()
    for d in docs:
        writer.update_document(**d)
    writer.commit()
    return len(docs)

def search_index(ix, query, limit=25):
    parser = MultifieldParser(["content", "program_title"], schema=ix.schema)
    with ix.searcher() as s:
        return s.search(parser.parse(query), limit=limit)

# UI
st.set_page_config(page_title=APP_NAME, page_icon="🎯", layout="wide")
st.title("🎯 DoD Budget Justification Keyword Scout")

with st.sidebar:
    st.header("Index Status")
    try:
        ix = whoosh_index.open_dir(INDEX_PATH)
        st.success(f"✅ {ix.searcher().doc_count():,} sections indexed")
    except:
        st.warning("No index yet")

tab1, tab2 = st.tabs(["📥 Upload & Index", "🔍 Search"])

with tab1:
    st.header("Upload Budget Justification PDFs")
    uploaded = st.file_uploader("Upload PDF(s)", type="pdf", accept_multiple_files=True)
    
    pdfs = []
    tmp_dir = None
    if uploaded:
        tmp_dir = tempfile.mkdtemp()
        for f in uploaded:
            p = os.path.join(tmp_dir, f.name)
            with open(p, "wb") as out:
                out.write(f.getbuffer())
            pdfs.append(p)
        st.success(f"✅ {len(uploaded)} file(s) ready")

    force = st.checkbox("Force full rebuild")
    
    if st.button("🚀 Scan & Build / Update Index", type="primary", disabled=not pdfs):
        if force and os.path.exists(INDEX_PATH):
            shutil.rmtree(INDEX_PATH)
        
        ix = get_or_create_index()
        total_added = 0
        
        progress = st.progress(0)
        status = st.empty()
        
        for i, path in enumerate(pdfs):
            filename = os.path.basename(path)
            status.text(f"Processing ({i+1}/{len(pdfs)}): {filename}")
            
            docs = process_pdf(path)
            if docs:
                added = add_to_index(ix, docs)
                total_added += added
                status.text(f"✅ Added {added} sections from {filename}")
            else:
                status.text(f"⚠️ No sections extracted from {filename}")
            
            progress.progress((i + 1) / len(pdfs))
        
        st.success(f"✅ Done! Indexed {total_added} sections from {len(pdfs)} files")
        if tmp_dir:
            shutil.rmtree(tmp_dir)
        st.rerun()

with tab2:
    st.header("Search Budget Justifications")
    q = st.text_input("Search keywords", value="harness OR connector OR payload")
    
    if st.button("🔎 Search"):
        try:
            ix = whoosh_index.open_dir(INDEX_PATH)
            results = search_index(ix, q)
            if not results:
                st.info("No matches found. Try different keywords.")
            else:
                st.success(f"Found {len(results)} results")
                for hit in results:
                    with st.expander(f"{hit.get('pe_number', 'Unknown')} — {hit.get('program_title', '')}"):
                        st.write(hit.get("content", "")[:900])
        except Exception as e:
            st.error(f"No index found or error: {e}")
            st.info("Please upload and index PDFs first in the Data Ingestion tab.")

st.caption("v2.7 • Fixed indexing • May 2026")