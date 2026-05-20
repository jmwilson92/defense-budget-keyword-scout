#!/usr/bin/env python3
"""
DoD Budget Justification Keyword Scout (BudgetPOC Scout)
Full UI + Grok AI Integration
"""

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
from openai import OpenAI

APP_NAME = "DoD Budget Justification Keyword Scout"
INDEX_PATH = "./whoosh_index"
CAPABILITIES_FILE = "my_capabilities.json"

# ==================== GROK API SETUP ====================
# Get your xAI API key from https://console.x.ai/
GROK_API_KEY = st.secrets.get("GROK_API_KEY", "")  # or hardcode for testing

def get_grok_client():
    if not GROK_API_KEY:
        st.error("Please add your Grok API key in the sidebar or secrets")
        return None
    return OpenAI(
        api_key=GROK_API_KEY,
        base_url="https://api.x.ai/v1"   # xAI Grok endpoint
    )

def grok_parse_pdf(text):
    """Use Grok to parse and structure PDF text"""
    client = get_grok_client()
    if not client:
        return None
    
    prompt = f"""You are an expert at parsing DoD budget justification documents.
    
Extract the following from the text below:
- Program Element (PE) number
- Program Title
- Mission Description / Justification summary (2-3 sentences)
- Key technologies or capabilities mentioned
- Funding amounts if available (current year + out years)
- Any Points of Contact or program office information

Return the result in clean JSON format with these keys:
pe_number, program_title, justification_summary, key_capabilities, funding, contacts

Text:
{text[:8000]}
"""
    
    try:
        response = client.chat.completions.create(
            model="grok-2-1212",   # or grok-beta
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=1500
        )
        return response.choices[0].message.content
    except Exception as e:
        st.error(f"Grok error: {e}")
        return None

def grok_find_pocs(pe_number, program_title):
    """Use Grok to generate smart POC research"""
    client = get_grok_client()
    if not client:
        return None
    
    prompt = f"""You are an expert defense industry business development professional.
    
For this Program Element: {pe_number} - {program_title}

Give me:
1. The 3 best LinkedIn search queries to find the actual Program Manager / TPOC
2. The best SBIR/STTR search strategy to find the TPOC name + email
3. 2-3 suggested email subject lines for cold outreach
4. Any known program office or command that owns this PE (if you know)

Be specific and actionable. Do not give generic advice.
"""
    
    try:
        response = client.chat.completions.create(
            model="grok-2-1212",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=1200
        )
        return response.choices[0].message.content
    except Exception as e:
        st.error(f"Grok error: {e}")
        return None

# ==================== REST OF YOUR EXISTING CODE ====================
# (Keep all your existing functions: clean_text, extract_pe, process_pdf, etc.)

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
    pe = "General"
    title = src.replace(".pdf", "")
    parts = []
    pages = []
    for i, page in enumerate(doc):
        txt = clean_text(page.get_text("text"))
        if len(txt) < 50: continue
        new_pe = extract_pe(txt)
        if new_pe and new_pe != pe:
            if parts:
                docs.append({"id": f"{src}_{pages[0]}_{pages[-1]}", "pe_number": pe, "program_title": title, "source": src, "pages": f"{pages[0]}-{pages[-1]}", "content": "\n\n".join(parts)})
            pe = new_pe
            title = txt.split('\n')[0][:60]
            parts = [txt]
            pages = [i+1]
        else:
            parts.append(txt)
            pages.append(i+1)
    if parts:
        docs.append({"id": f"{src}_{pages[0]}_{pages[-1]}", "pe_number": pe, "program_title": title, "source": src, "pages": f"{pages[0]}-{pages[-1]}", "content": "\n\n".join(parts)})
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
    w = ix.writer()
    for d in docs:
        w.update_document(**d)
    w.commit()
    return len(docs)

def search_index(query, limit=25):
    try:
        ix = whoosh_index.open_dir(INDEX_PATH)
        parser = MultifieldParser(["content", "program_title"], schema=ix.schema)
        with ix.searcher() as s:
            results = s.search(parser.parse(query), limit=limit)
            return [{"pe_number": r.get("pe_number", "Unknown"), 
                    "program_title": r.get("program_title", ""), 
                    "content": r.get("content", "")[:900]} for r in results]
    except:
        return []

def load_capabilities():
    if os.path.exists(CAPABILITIES_FILE):
        try:
            return json.load(open(CAPABILITIES_FILE))["keywords"]
        except:
            pass
    return DEFAULT_CAPABILITIES

def save_capabilities(keywords):
    json.dump({"keywords": keywords}, open(CAPABILITIES_FILE, "w"))

# ==================== UI ====================
st.set_page_config(page_title=APP_NAME, page_icon="🎯", layout="wide")
st.title("🎯 DoD Budget Justification Keyword Scout")
st.caption("Search official DoD budget justifications • Target keywords • Research POCs • Built for defense contractors & SDVOSBs")

with st.sidebar:
    st.header("Index Status")
    try:
        ix = whoosh_index.open_dir(INDEX_PATH)
        with ix.searcher() as s:
            count = s.doc_count()
        st.success(f"✅ {count:,} sections indexed")
    except:
        st.warning("No index yet")

    st.divider()
    st.header("Grok AI Settings")
    api_key = st.text_input("xAI API Key", type="password", value=GROK_API_KEY)
    if api_key:
        GROK_API_KEY = api_key

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "📥 Data Ingestion", 
    "🔍 Search & Target", 
    "⭐ My Capabilities", 
    "🧭 POC Research Helper", 
    "🤖 Grok AI Assistant",
    "ℹ️ Help & About"
])

# Tab 1-4 remain the same as your current clean version (Data Ingestion, Search, Capabilities, POC Helper)

# ========== TAB 5: GROK AI ASSISTANT (NEW) ==========
with tab5:
    st.header("🤖 Grok AI Assistant")
    st.markdown("Use Grok to parse PDFs, find real POCs, and generate professional outreach materials.")

    option = st.radio("What would you like Grok to help with?", 
                      ["Parse PDF & Extract Structured Data", 
                       "Find Real POCs for a Program", 
                       "Generate Outreach Email"])

    if option == "Parse PDF & Extract Structured Data":
        uploaded = st.file_uploader("Upload a PDF for Grok to analyze", type="pdf")
        if uploaded and st.button("Analyze with Grok"):
            with st.spinner("Grok is reading and structuring the document..."):
                text = ""
                with fitz.open(stream=uploaded.read(), filetype="pdf") as doc:
                    for page in doc:
                        text += page.get_text()
                
                result = grok_parse_pdf(text)
                if result:
                    st.subheader("Grok's Structured Output")
                    st.json(result)

    elif option == "Find Real POCs for a Program":
        pe = st.text_input("Program Element")
        title = st.text_input("Program Title (optional)")
        
        if st.button("Ask Grok to Find POCs"):
            with st.spinner("Grok is researching..."):
                result = grok_find_pocs(pe, title)
                if result:
                    st.subheader("Grok's POC Research")
                    st.markdown(result)

    elif option == "Generate Outreach Email":
        pe = st.text_input("Program Element")
        title = st.text_input("Program Title")
        your_company = st.text_input("Your Company / Capability")
        
        if st.button("Generate Email with Grok"):
            # Add email generation prompt here
            st.info("Email generation coming in next update")

# Tab 6 (Help) stays the same

st.divider()
st.caption("v4.0 • Grok AI Powered • May 2026")