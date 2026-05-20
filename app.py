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
    st.write(f"**Starting to process:** {os.path.basename(path)}")
    docs = []
    try:
        doc = fitz.open(path)
        st.write(f"✅ Opened PDF with {len(doc)} pages")
    except Exception as e:
        st.error(f"❌ Failed to open PDF: {e}")
        return docs
    
    src = os.path.basename(path)
    pe = "General"
    title = src.replace(".pdf", "")
    parts = []
    pages = []
    
    for i, page in enumerate(doc):
        txt = clean_text(page.get_text("text"))
        if len(txt) < 30:
            continue
        new_pe = extract_pe(txt)
        if new_pe and new_pe != pe:
            if parts:
                docs.append({
                    "id": f"{src}_{pages[0]}_{pages[-1]}",
                    "pe_number": pe,
                    "program_title": title,
                    "source": src,
                    "pages": f"{pages[0]}-{pages[-1]}",
                    "content": "\n\n".join(parts)
                })
            pe = new_pe
            title = txt.split('\n')[0][:60]
            parts = [txt]
            pages = [i+1]
        else:
            parts.append(txt)
            pages.append(i+1)
    
    if parts:
        docs.append({
            "id": f"{src}_{pages[0]}_{pages[-1]}",
            "pe_number": pe,
            "program_title": title,
            "source": src,
            "pages": f"{pages[0]}-{pages[-1]}",
            "content": "\n\n".join(parts)
        })
    
    st.write(f"✅ Extracted {len(docs)} sections from {src}")
    doc.close()
    return docs

def get_index():
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
    w = ix.writer()
    for d in docs:
        w.update_document(**d)
    w.commit()
    return len(docs)

def search_index(ix, q, limit=20):
    p = MultifieldParser(["content", "program_title"], schema=ix.schema)
    with ix.searcher() as s:
        return s.search(p.parse(q), limit=limit)

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
    tmp = None
    if uploaded:
        tmp = tempfile.mkdtemp()
        for f in uploaded:
            p = os.path.join(tmp, f.name)
            with open(p, "wb") as out: out.write(f.getbuffer())
            pdfs.append(p)
        st.success(f"✅ {len(uploaded)} file(s) ready to process")

    if st.button("🚀 Scan & Build / Update Index", type="primary", disabled=not pdfs):
        st.write("### Starting indexing process...")
        ix = get_index()
        total = 0
        
        for i, path in enumerate(pdfs):
            st.write(f"**--- Processing file {i+1}/{len(pdfs)} ---**")
            docs = process_pdf(path)
            if docs:
                added = add_to_index(ix, docs)
                total += added
                st.write(f"✅ Successfully added {added} sections")
            else:
                st.write("⚠️ No sections were extracted from this PDF")
        
        st.success(f"### ✅ FINISHED! Total sections indexed: {total}")
        if tmp: shutil.rmtree(tmp)
        st.rerun()

with tab2:
    st.header("Search Budget Justifications")
    q = st.text_input("Keywords", value="harness OR connector OR payload")
    
    if st.button("🔎 Search"):
        try:
            ix = whoosh_index.open_dir(INDEX_PATH)
            results = search_index(ix, q)
            if not results:
                st.info("No matches found")
            for hit in results:
                with st.expander(f"{hit.get('pe_number')} — {hit.get('program_title', '')}"):
                    st.write(hit.get("content", "")[:800])
        except:
            st.warning("No index yet. Upload PDFs first.")

st.caption("v3.2 • Heavy Logging Version • May 2026")