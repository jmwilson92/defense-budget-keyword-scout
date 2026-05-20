#!/usr/bin/env python3
"""
DoD Budget Justification Keyword Scout (BudgetPOC Scout)
Streamlit app for defense contractors to search budget justifications,
target keywords in line items / program elements, and research POCs/outreach.
"""

import os
import re
import json
import time
import shutil
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Tuple, Optional, Any

import streamlit as st
import fitz  # PyMuPDF
import pandas as pd
from whoosh import index as whoosh_index
from whoosh.fields import Schema, TEXT, ID, STORED, KEYWORD
from whoosh.analysis import StemmingAnalyzer, StandardAnalyzer
from whoosh.qparser import MultifieldParser, QueryParser
from whoosh.searching import Results
from whoosh.highlight import Highlighter, UppercaseFormatter
import webbrowser
from urllib.parse import quote_plus

# ----------------------------- CONFIG -----------------------------
APP_NAME = "DoD Budget Justification Keyword Scout"
INDEX_DIR_NAME = "whoosh_index"
CAPABILITIES_FILE = "my_capabilities.json"
DEFAULT_INDEX_PATH = "./whoosh_index"  # relative; user can change

# Curated starter keywords relevant to precision defense manufacturing
# (harnesses, connectors, electro-mechanical, MIL-SPEC, avionics, etc.)
DEFAULT_CAPABILITIES = [
    "D38999", "MIL-DTL-38999", "Glenair", "Amphenol", "backshell", "back shell",
    "harness", "harnesses", "cable assembly", "cable assemblies", "wiring harness",
    "coax", "RG400", "RG-400", "connector", "connectors", "interconnect",
    "overmold", "overmolding", "potting", "potting compound", "MIL-A-46146",
    "heat shrink", "strain relief", "crimp", "crimping", "crimp tool", "pin tool",
    "IPC-A-620", "IPC A-620", "AS9100", "AS9100D", "MIL-STD", "MIL-STD-1553",
    "avionics", "electro-mechanical", "electromechanical", "payload", "payloads",
    "wire harness", "cabling", "interconnection", "molding", "encapsulation",
    "D38999 Series", "Glenair backshell", "connector assembly", "harness assembly",
    "MIL-SPEC", "defense interconnect", "aerospace harness", "space harness",
    "flight hardware", "ground support equipment", "test harness", "integration harness"
]

# Regex patterns for detecting Program Element numbers and titles
PE_PATTERNS = [
    r'PE\s+(\d{7}[A-Z]?)',                           # PE 0601234N
    r'Program Element\s*\(Number/Name\)\s*[:\s]*(\d{7}[A-Z]?)',  # from R-1 exhibit
    r'R-1 Program Element.*?(\d{7}[A-Z]?)',          # R-1 header
    r'Exhibit R-2.*?PE\s+(\d{7}[A-Z]?)',             # R-2 exhibit
    r'(\d{7}[A-Z]?)\s*/\s*([A-Z][A-Za-z0-9\s\-]+)',  # sometimes "0601234N / Project Title"
]

TITLE_PATTERNS = [
    r'PE\s+\d{7}[A-Z]?\s*[:\-]?\s*([A-Za-z][A-Za-z0-9\s\-\(\)]{5,80})',
    r'Program Element.*?[:\-]\s*([A-Za-z][A-Za-z0-9\s\-\(\)]{5,80})',
]

def clean_text(text: str) -> str:
    """Basic cleaning for PDF-extracted text."""
    if not text:
        return ""
    # Normalize whitespace
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    # Remove very common boilerplate that pollutes search
    boilerplate = [
        r'\bUNCLASSIFIED\b',
        r'\bPage \d+ of \d+\b',
        r'THIS PAGE INTENTIONALLY LEFT BLANK',
        r'Department of Defense Fiscal Year \(FY\) \d{4} Budget Estimates',
        r'Office of the Secretary Of Defense',
    ]
    for bp in boilerplate:
        text = re.sub(bp, '', text, flags=re.IGNORECASE)
    return text.strip()

def extract_pe_info(text: str) -> Tuple[Optional[str], Optional[str]]:
    """Try to extract PE number and a program title from a chunk of text."""
    pe_number = None
    title = None

    for pattern in PE_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if match:
            pe_number = match.group(1).strip().upper()
            break

    if pe_number:
        # Try to get a title near the PE number
        for tpat in TITLE_PATTERNS:
            tmatch = re.search(tpat, text, re.IGNORECASE)
            if tmatch:
                candidate = tmatch.group(1).strip()
                if len(candidate) > 8 and not candidate.lower().startswith(('pe ', 'program')):
                    title = candidate[:80]
                    break
        if not title:
            # Fallback: take the line after the PE match if reasonable
            lines = text.split('\n')
            for i, line in enumerate(lines):
                if pe_number in line.upper():
                    if i + 1 < len(lines):
                        next_line = lines[i+1].strip()
                        if 10 < len(next_line) < 100 and not next_line[0].isdigit():
                            title = next_line[:80]
                            break

    return pe_number, title

def get_pdf_metadata(pdf_path: str) -> Dict[str, Any]:
    """Extract basic metadata from PDF."""
    try:
        doc = fitz.open(pdf_path)
        meta = {
            "title": doc.metadata.get("title", ""),
            "author": doc.metadata.get("author", ""),
            "subject": doc.metadata.get("subject", ""),
            "page_count": len(doc),
        }
        doc.close()
        return meta
    except Exception:
        return {"title": "", "author": "", "subject": "", "page_count": 0}

def process_pdf_to_documents(pdf_path: str) -> List[Dict[str, Any]]:
    """
    Extract text from PDF, attempt to segment into Program Element sections,
    and return list of document dicts ready for indexing.
    """
    documents = []
    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        st.error(f"Failed to open {pdf_path}: {e}")
        return documents

    source_name = os.path.basename(pdf_path)
    current_pe = "General Overview / Front Matter"
    current_title = source_name.replace(".pdf", "").replace("_", " ")
    current_text_parts: List[str] = []
    current_pages: List[int] = []
    min_chunk_chars = 300  # skip tiny fragments

    for page_num in range(len(doc)):
        page = doc[page_num]
        raw_text = page.get_text("text")
        text = clean_text(raw_text)

        if len(text) < 50:
            continue

        new_pe, new_title = extract_pe_info(text)

        if new_pe and new_pe != current_pe:
            # Flush previous section if substantial
            if current_text_parts:
                full_text = "\n\n".join(current_text_parts)
                if len(full_text) >= min_chunk_chars:
                    documents.append({
                        "id": f"{source_name}_{current_pages[0] if current_pages else 1}_{current_pages[-1] if current_pages else 1}",
                        "pe_number": current_pe,
                        "program_title": current_title,
                        "source": source_name,
                        "pages": f"{current_pages[0] if current_pages else 1}-{current_pages[-1] if current_pages else 1}",
                        "content": full_text,
                        "page_start": current_pages[0] if current_pages else 1,
                        "page_end": current_pages[-1] if current_pages else 1,
                    })
            # Start new section
            current_pe = new_pe
            current_title = new_title or current_title
            current_text_parts = [text]
            current_pages = [page_num + 1]
        else:
            current_text_parts.append(text)
            current_pages.append(page_num + 1)

    # Flush the last section
    if current_text_parts:
        full_text = "\n\n".join(current_text_parts)
        if len(full_text) >= min_chunk_chars:
            documents.append({
                "id": f"{source_name}_{current_pages[0] if current_pages else 1}_{current_pages[-1] if current_pages else 1}",
                "pe_number": current_pe,
                "program_title": current_title,
                "source": source_name,
                "pages": f"{current_pages[0] if current_pages else 1}-{current_pages[-1] if current_pages else 1}",
                "content": full_text,
                "page_start": current_pages[0] if current_pages else 1,
                "page_end": current_pages[-1] if current_pages else 1,
            })

    doc.close()
    return documents

def create_or_open_index(index_path: str) -> Any:
    """Create Whoosh index if it doesn't exist, else open it."""
    schema = Schema(
        id=ID(stored=True, unique=True),
        pe_number=KEYWORD(stored=True, commas=True),
        program_title=TEXT(stored=True, analyzer=StandardAnalyzer()),
        source=TEXT(stored=True),
        pages=STORED(),
        content=TEXT(stored=True, analyzer=StemmingAnalyzer()),
        page_start=STORED(),
        page_end=STORED(),
    )

    if not os.path.exists(index_path):
        os.makedirs(index_path, exist_ok=True)
        ix = whoosh_index.create_in(index_path, schema)
    else:
        try:
            ix = whoosh_index.open_dir(index_path)
        except Exception:
            # Corrupted or old schema — recreate
            shutil.rmtree(index_path)
            os.makedirs(index_path, exist_ok=True)
            ix = whoosh_index.create_in(index_path, schema)
    return ix

def add_documents_to_index(ix: Any, documents: List[Dict[str, Any]], show_progress: bool = False) -> int:
    """Add or update documents in the Whoosh index."""
    writer = ix.writer()
    count = 0
    for doc in documents:
        try:
            writer.update_document(
                id=doc["id"],
                pe_number=doc.get("pe_number", "Unknown"),
                program_title=doc.get("program_title", ""),
                source=doc.get("source", ""),
                pages=doc.get("pages", ""),
                content=doc.get("content", ""),
                page_start=doc.get("page_start", 0),
                page_end=doc.get("page_end", 0),
            )
            count += 1
        except Exception as e:
            if show_progress:
                st.warning(f"Skipping document {doc.get('id')}: {e}")
    writer.commit()
    return count

def search_index(ix: Any, query_str: str, limit: int = 30) -> Results:
    """Perform search and return Whoosh Results."""
    parser = MultifieldParser(["content", "program_title"], schema=ix.schema)
    try:
        q = parser.parse(query_str)
    except Exception:
        # Fallback to simple query
        q = QueryParser("content", ix.schema).parse(query_str)
    with ix.searcher() as searcher:
        results = searcher.search(q, limit=limit)
        return results

def highlight_text(text: str, keywords: List[str], max_chars: int = 600) -> str:
    """Simple highlight for display (Whoosh highlighter is better but this is fallback)."""
    if not keywords:
        return text[:max_chars] + ("..." if len(text) > max_chars else "")
    highlighted = text
    for kw in sorted(keywords, key=len, reverse=True):
        if kw:
            pattern = re.compile(re.escape(kw), re.IGNORECASE)
            highlighted = pattern.sub(lambda m: f"**{m.group(0)}**", highlighted)
    if len(highlighted) > max_chars:
        highlighted = highlighted[:max_chars] + "..."
    return highlighted

def load_capabilities() -> List[str]:
    """Load user's saved capabilities/keywords from JSON."""
    if os.path.exists(CAPABILITIES_FILE):
        try:
            with open(CAPABILITIES_FILE, "r") as f:
                data = json.load(f)
                return data.get("keywords", DEFAULT_CAPABILITIES)
        except Exception:
            pass
    return DEFAULT_CAPABILITIES.copy()

def save_capabilities(keywords: List[str]):
    """Persist user's keywords."""
    with open(CAPABILITIES_FILE, "w") as f:
        json.dump({"keywords": keywords, "updated": datetime.now().isoformat()}, f, indent=2)

def score_document_against_keywords(content: str, keywords: List[str]) -> Tuple[int, List[str]]:
    """Return (match_count, matched_keywords) for a document."""
    if not content or not keywords:
        return 0, []
    content_lower = content.lower()
    matched = []
    for kw in keywords:
        if kw.lower() in content_lower:
            matched.append(kw)
    return len(matched), matched

def get_all_indexed_documents(ix: Any) -> List[Dict[str, Any]]:
    """Retrieve lightweight metadata for all docs in index (for capability scoring)."""
    docs = []
    with ix.searcher() as searcher:
        for doc in searcher.all_stored_fields():
            docs.append({
                "id": doc.get("id"),
                "pe_number": doc.get("pe_number", "Unknown"),
                "program_title": doc.get("program_title", ""),
                "source": doc.get("source", ""),
                "pages": doc.get("pages", ""),
                "content": doc.get("content", "")[:2000],  # truncate for memory
            })
    return docs

def open_search_in_browser(query: str, engine: str = "google"):
    """Open a pre-filled search in the user's browser."""
    if engine == "google":
        url = f"https://www.google.com/search?q={quote_plus(query)}"
    elif engine == "linkedin":
        url = f"https://www.linkedin.com/search/results/all/?keywords={quote_plus(query)}"
    elif engine == "sam":
        url = f"https://sam.gov/search/?index=opp&q={quote_plus(query)}&sort=-relevance"
    else:
        url = f"https://www.google.com/search?q={quote_plus(query)}"
    webbrowser.open_new_tab(url)

def build_poc_queries(pe_number: str, program_title: str, matched_keywords: List[str]) -> Dict[str, str]:
    """Generate useful search queries for POC / opportunity research."""
    base = f'"{pe_number}" "{program_title}"' if program_title else f'"{pe_number}"'
    kw_str = " OR ".join([f'"{k}"' for k in matched_keywords[:5]]) if matched_keywords else ""

    queries = {
        "Google - Program Manager / TPOC": f'{base} ("Program Manager" OR PM OR TPOC OR "Technical Point of Contact" OR "Contracting Officer" OR KO) (Navy OR "Air Force" OR Army OR DARPA OR MDA OR SOCOM OR "Space Force")',
        "LinkedIn - Program Leadership": f'{base} ("Program Manager" OR "Technical Director" OR TPOC) (defense OR aerospace OR "program office")',
        "SBIR / STTR for this PE": f'{pe_number} OR "{program_title}" site:sbir.gov OR site:sttr.gov',
        "Recent Awards / Spending": f'{base} OR "{program_title}" (award OR contract OR "program element") site:usaspending.gov',
        "SAM.gov Opportunities": " ".join(matched_keywords[:4]) + " defense OR navy OR air force harness OR connector OR avionics",
    }
    return queries

# ----------------------------- STREAMLIT UI -----------------------------
st.set_page_config(
    page_title=APP_NAME,
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("🎯 DoD Budget Justification Keyword Scout")
st.caption("Search official DoD budget justifications & descriptive summaries • Target keywords in line items • Research POCs & initiate conversations • Built for defense contractors & SDVOSBs")

# Sidebar - Index status & quick actions
with st.sidebar:
    st.header("Index Status")
    index_path = st.text_input("Whoosh Index Location", value=DEFAULT_INDEX_PATH, help="Where the search index is stored on disk")
    
    ix = None
    index_exists = os.path.exists(os.path.join(index_path, "MAIN_write.lock")) or os.path.exists(os.path.join(index_path, "_MAIN_1.toc"))
    
    if index_exists:
        try:
            ix = whoosh_index.open_dir(index_path)
            with ix.searcher() as searcher:
                doc_count = searcher.doc_count()
            st.success(f"✅ Index ready — {doc_count:,} sections indexed")
        except Exception as e:
            st.error(f"Index error: {e}. Try rebuilding.")
            index_exists = False
    else:
        st.warning("No index found. Go to Data Ingestion tab to build one.")

    st.divider()
    st.header("Quick Tips")
    st.markdown("""
    - Start with **My Capabilities** tab to score everything against what you actually make.
    - Use specific keywords: `D38999 harness` beats generic `connector`.
    - For best results, index 3–8 high-value PDFs first (e.g. Navy RDT&E + DARPA).
    - POCs are rarely in the PDFs — use the generated searches to find them on LinkedIn / program sites.
    """)

# Main tabs
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📥 Data Ingestion", 
    "🔍 Search & Target", 
    "⭐ My Capabilities & Best Matches", 
    "🧭 POC Research Helper", 
    "ℹ️ Help & About"
])

# ========== TAB 1: DATA INGESTION ==========
with tab1:
    st.header("Ingest & Index Budget Justification PDFs")
    st.markdown("""
    **Step 1**: Download PDFs from the official Comptroller site (see Help tab for links).  
    **Step 2**: Point this tool at the folder containing them (it scans recursively for `*.pdf`).  
    **Step 3**: Click **Scan & Build / Update Index**. This may take several minutes the first time.
    """)

    pdf_dir = st.text_input(
        "Path to folder containing justification PDFs",
        value="~/DoD_Budgets/FY2026_Justifications",
        help="Use absolute path. The tool will find all .pdf files under this directory (including subfolders)."
    )

    col_a, col_b = st.columns(2)
    with col_a:
        force_rebuild = st.checkbox("Force full rebuild (delete old index)", value=False)
    with col_b:
        max_pdfs = st.number_input("Max PDFs to process (0 = all)", min_value=0, value=0, step=1, help="Useful for testing with a subset")

    if st.button("🚀 Scan & Build / Update Index", type="primary", disabled=not pdf_dir):
        pdf_dir_expanded = os.path.expanduser(pdf_dir)
        if not os.path.isdir(pdf_dir_expanded):
            st.error(f"Directory not found: {pdf_dir_expanded}")
        else:
            pdf_files = list(Path(pdf_dir_expanded).rglob("*.pdf"))
            if max_pdfs > 0:
                pdf_files = pdf_files[:max_pdfs]
            
            if not pdf_files:
                st.warning("No PDF files found in that directory.")
            else:
                st.info(f"Found {len(pdf_files)} PDF(s). Starting extraction and indexing...")

                if force_rebuild and os.path.exists(index_path):
                    shutil.rmtree(index_path)
                    st.warning("Old index deleted.")

                ix = create_or_open_index(index_path)

                progress_bar = st.progress(0.0)
                status_text = st.empty()
                total_docs_added = 0
                start_time = time.time()

                for idx, pdf_path in enumerate(pdf_files):
                    status_text.text(f"Processing ({idx+1}/{len(pdf_files)}): {pdf_path.name}")
                    docs = process_pdf_to_documents(str(pdf_path))
                    added = add_documents_to_index(ix, docs, show_progress=False)
                    total_docs_added += added
                    progress_bar.progress((idx + 1) / len(pdf_files))

                elapsed = time.time() - start_time
                status_text.text(f"✅ Done in {elapsed:.1f}s — {total_docs_added:,} sections indexed from {len(pdf_files)} PDFs.")
                st.balloons()
                st.success("Index updated! Switch to Search or My Capabilities tabs.")
                # Force reload of index in session
                st.rerun()

    st.divider()
    st.subheader("What gets indexed?")
    st.markdown("""
    - The tool tries to segment text into **Program Element (PE)** sections using common patterns in R-2 / R-3 exhibits.
    - Pages without a clear PE go into "General Overview / Front Matter".
    - Only substantial text chunks (> ~300 chars) are kept.
    - Both RDT&E (rich descriptions) and Procurement justification books work.
    """)

# ========== TAB 2: SEARCH & TARGET ==========
with tab2:
    st.header("Keyword Search Across Budget Justifications")
    st.caption("Enter keywords or Whoosh query syntax. Results are ranked by relevance to your search.")

    if not index_exists or ix is None:
        st.warning("Please build or load an index first in the Data Ingestion tab.")
    else:
        query = st.text_input(
            "Search query (keywords, phrases in \"quotes\", +must +have for AND)",
            value="D38999 OR harness OR \"cable assembly\" OR backshell",
            placeholder="e.g. harness connector D38999 OR \"electro-mechanical\" +avionics",
            help="Whoosh syntax supported: +keyword (must), -keyword (not), \"exact phrase\", keyword~ (fuzzy)"
        )

        col1, col2, col3 = st.columns(3)
        with col1:
            limit = st.slider("Max results", 5, 100, 25, step=5)
        with col2:
            min_score = st.slider("Min score (optional)", 0.0, 20.0, 0.0, step=0.5)
        with col3:
            filter_source = st.text_input("Filter by source contains (optional)", placeholder="Navy or DARPA")

        if st.button("🔎 Search", type="primary"):
            with st.spinner("Searching index..."):
                results = search_index(ix, query, limit=limit)

            if not results:
                st.info("No matches found. Try broader keywords or check your index.")
            else:
                st.success(f"Found {len(results)} results (showing top {min(len(results), limit)})")
                
                for i, hit in enumerate(results):
                    score = hit.score
                    if min_score > 0 and score < min_score:
                        continue

                    pe = hit.get("pe_number", "Unknown")
                    title = hit.get("program_title", "")
                    source = hit.get("source", "")
                    pages = hit.get("pages", "")
                    content = hit.get("content", "")

                    # Simple keyword extraction from query for highlighting
                    query_keywords = re.findall(r'[\w\-]+', query.lower())

                    with st.expander(f"**{pe}** — {title or 'Program Description'}  |  {source} (pp. {pages})  |  score: {score:.2f}", expanded=(i < 3)):
                        st.markdown(f"**Source:** {source} &nbsp;&nbsp;|&nbsp;&nbsp; **Pages:** {pages}")
                        if title:
                            st.markdown(f"**Program Title:** {title}")

                        # Highlighted snippet
                        snippet = highlight_text(content, query_keywords, max_chars=800)
                        st.markdown(snippet, unsafe_allow_html=True)

                        # Full text toggle
                        if st.checkbox(f"Show full extracted text for this section", key=f"full_{i}"):
                            st.text_area("Full text", content, height=300, key=f"ta_{i}")

                        # Quick action to POC helper
                        if st.button(f"🧭 Research POC & Opportunities for this item", key=f"poc_{i}"):
                            st.session_state["selected_hit"] = {
                                "pe_number": pe,
                                "program_title": title,
                                "source": source,
                                "pages": pages,
                                "content": content[:1500],
                                "matched_keywords": query_keywords,
                            }
                            st.switch_page("🧭 POC Research Helper")  # This won't work in tabs; use info instead
                            st.info("Scroll down or switch to the **POC Research Helper** tab. Your selection is loaded there.")

# ========== TAB 3: MY CAPABILITIES & BEST MATCHES ==========
with tab3:
    st.header("⭐ Score Everything Against *Your* Capabilities")
    st.markdown("Edit the list below with the exact keywords/phrases that describe what you sell or do. The tool will score every indexed section and show you the **best matching funded programs**.")

    capabilities = load_capabilities()

    with st.expander("Edit / Customize My Keywords (saved automatically)", expanded=True):
        # Allow editing as a text area for simplicity
        caps_text = st.text_area(
            "One keyword or phrase per line",
            value="\n".join(capabilities),
            height=200,
            help="Add very specific terms: your processes, part numbers you support, platforms, certifications, etc."
        )
        new_caps = [line.strip() for line in caps_text.split("\n") if line.strip()]
        
        col_save1, col_save2 = st.columns([1, 3])
        with col_save1:
            if st.button("💾 Save Keywords"):
                save_capabilities(new_caps)
                st.success("Keywords saved!")
                capabilities = new_caps  # update local
                st.rerun()
        with col_save2:
            if st.button("↩️ Reset to Defaults"):
                save_capabilities(DEFAULT_CAPABILITIES)
                st.rerun()

    st.divider()

    if not index_exists or ix is None:
        st.info("Build an index first to score documents.")
    else:
        if st.button("🚀 Find Best Matches for My Capabilities", type="primary"):
            with st.spinner("Scoring all indexed sections against your keywords... (can take 10-60s depending on index size)"):
                all_docs = get_all_indexed_documents(ix)
                scored = []
                for d in all_docs:
                    count, matched = score_document_against_keywords(d.get("content", ""), capabilities)
                    if count > 0:
                        scored.append({
                            **d,
                            "match_count": count,
                            "matched_keywords": ", ".join(matched[:8]),
                        })
                scored.sort(key=lambda x: x["match_count"], reverse=True)

            if not scored:
                st.warning("No matches found. Try adding more or different keywords, or check that your index has descriptive text.")
            else:
                st.success(f"Top matches: {len(scored)} sections contain at least one of your keywords. Showing highest overlap first.")
                df = pd.DataFrame(scored[:50])  # top 50
                st.dataframe(
                    df[["pe_number", "program_title", "source", "pages", "match_count", "matched_keywords"]],
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "match_count": st.column_config.NumberColumn("Keyword Matches", help="How many of your keywords appear in the justification text"),
                    }
                )

                # Export
                csv = df.to_csv(index=False).encode("utf-8")
                st.download_button(
                    "📥 Download Top Matches as CSV",
                    csv,
                    file_name=f"budget_matches_{datetime.now().strftime('%Y%m%d')}.csv",
                    mime="text/csv",
                )

                st.caption("Use the PE numbers and program titles above to jump into the POC Research Helper or run targeted searches in Tab 2.")

# ========== TAB 4: POC RESEARCH HELPER ==========
with tab4:
    st.header("🧭 POC & Opportunity Research Helper")
    st.markdown("""
    Budget justifications rarely contain direct emails. This panel helps you **generate precise, high-signal search queries** 
    so you can quickly find Program Managers, Technical POCs, Contracting Officers, or related opportunities on LinkedIn, Google, SBIR.gov, SAM.gov, and USAspending.gov.
    """)

    # Allow manual entry or pull from session if user came from search
    default_pe = ""
    default_title = ""
    default_kws = ""

    if "selected_hit" in st.session_state:
        hit = st.session_state["selected_hit"]
        default_pe = hit.get("pe_number", "")
        default_title = hit.get("program_title", "")
        default_kws = ", ".join(hit.get("matched_keywords", []))
        st.info(f"Loaded from previous search: **{default_pe}** — {default_title}")

    col_pe, col_title = st.columns(2)
    with col_pe:
        pe_number = st.text_input("Program Element (PE) Number", value=default_pe, placeholder="0601234N or 0603176C")
    with col_title:
        program_title = st.text_input("Program Title / Name", value=default_title, placeholder="Advanced Avionics Interconnect or similar")

    matched_kws_str = st.text_input("Keywords that matched (comma separated)", value=default_kws)
    matched_keywords = [k.strip() for k in matched_kws_str.split(",") if k.strip()]

    if st.button("Generate Research Queries & Links", type="primary"):
        if not pe_number and not program_title:
            st.warning("Enter at least a PE number or program title for best results.")
        else:
            queries = build_poc_queries(pe_number, program_title, matched_keywords)

            st.subheader("Ready-to-Use Search Queries")
            for label, q in queries.items():
                with st.expander(label, expanded=True):
                    st.code(q, language=None)
                    if st.button(f"🔗 Open this search in browser", key=f"open_{label}"):
                        if "Google" in label or "Awards" in label:
                            open_search_in_browser(q, "google")
                        elif "LinkedIn" in label:
                            open_search_in_browser(q, "linkedin")
                        elif "SAM" in label:
                            open_search_in_browser(q, "sam")
                        else:
                            open_search_in_browser(q)

            st.divider()
            st.subheader("Direct Action Links")
            # Pre-filled SAM link
            sam_query = quote_plus(" ".join(matched_keywords[:5]) or program_title or pe_number)
            sam_url = f"https://sam.gov/search/?index=opp&q={sam_query}&sort=-relevance&sfm%5Bstatus%5D%5Bis_active%5D=true"
            if st.button("🛒 Open SAM.gov Opportunities Search"):
                webbrowser.open_new_tab(sam_url)

            st.markdown("""
            **Next Steps After Searching**:
            1. On LinkedIn/Google results, look for people with titles like "Program Manager, [PE or Platform]", "TPOC for [Program]", "Contracting Officer [Agency]".
            2. Check the specific Program Office website (e.g., PMA-XXX for Navy, or DARPA program page) — many list Industry Day info or small business points of contact.
            3. Search USAspending.gov for the PE or program name + recent years → see who won similar work and who the KO/ COR was.
            4. SBIR/STTR topics under that PE often list the exact TPOC name + email.
            5. Craft a short, specific capability email/note referencing the exact justification language you found ("I saw the FY26 request for advanced interconnect solutions supporting the [program] described on page X...").
            """)

# ========== TAB 5: HELP & ABOUT ==========
with tab5:
    st.header("Help, Sources & Best Practices")
    
    with st.expander("Where to Download the Official Budget Justification PDFs", expanded=True):
        st.markdown("""
        **Primary Source**: [Under Secretary of Defense (Comptroller) Budget Materials](https://comptroller.defense.gov/Budget-Materials/)
        
        - Go to the current FY (FY2026 / FY2027 etc.)
        - Look for **Budget Justification** or **Detailed Budget Documents** sections.
        - Key volumes usually include:
          - RDT&E Defense-Wide (multiple volumes: DARPA, MDA, SOCOM, OSD, etc.)
          - Service RDT&E and Procurement justification books (Navy, Air Force, Army)
        - Direct example paths (may vary slightly by year):
          - `.../budget_justification/pdfs/03_RDT_and_E/RDTE_Vol1_DARPA_MasterJustificationBook_PB_2026.pdf`
        
        **Service-specific sites** (sometimes have more or earlier releases):
        - Navy: asafm.navy.mil or similar comptroller pages
        - Army: asafm.army.mil/Budget-Materials/
        - Air Force: often linked from main comptroller site
        
        **Tip for contractors in San Diego / Navy-Marine ecosystem**: Prioritize Navy RDT&E and Procurement volumes first — lots of E-2, helicopter, shipboard avionics, and payload work.
        """)

    with st.expander("Understanding the Data (R-2, R-3, Mission Description, etc.)"):
        st.markdown("""
        - **Program Element (PE)**: The main "line item" identifier (e.g., 0601234N). This is what you target.
        - **Mission Description and Budget Item Justification**: Narrative paragraphs explaining *why* the money is requested and *what technical work* is planned. This is the richest text for keyword matching.
        - **Accomplishments / Planned Programs**: What they did last year and what they intend to do with the new money. Gold for capability alignment.
        - **Exhibit R-2 / R-2A / R-3**: Structured budget forms. The tool extracts the surrounding text.
        - Procurement books have shorter "Justification" paragraphs per P-1 line item.
        """)

    with st.expander("Best Practices for Outreach"):
        st.markdown("""
        - **Be specific**: Reference the exact program need or technology gap you saw in the justification. "I noticed the FY26 plans for next-generation interconnect solutions supporting [platform]..."
        - **Lead with value**: Mention relevant past performance (even if CUI or limited) or unique capabilities (specific connector series, IPC certification, SDVOSB set-aside eligibility, rapid prototyping, etc.).
        - **Multi-channel**: LinkedIn + email (if found) + attend the right industry days / AUSA / Sea-Air-Space / SOF Week.
        - **Primes**: Many PEs are executed via primes (Lockheed, Northrop, Boeing, L3Harris, etc.). Finding the prime's supply chain contact for that program can be faster than the government PM.
        - **SBIR/STTR bridge**: If a PE has related SBIR topics, the TPOC listed is often very approachable.
        - **Timing**: Right after budget release or after appropriations bill passes is when PMs are thinking about execution and industry partners.
        """)

    st.divider()
    st.subheader("About This Tool")
    st.markdown(f"""
    **{APP_NAME}** was built to give defense contractors — especially small businesses and SDVOSBs without expensive subscription intelligence platforms — a practical, local, no-cost way to mine the public budget justification books.

    It uses:
    - **PyMuPDF (fitz)** for fast, high-quality PDF text extraction
    - **Whoosh** for fast, pure-Python full-text search with stemming and highlighting
    - **Streamlit** for the friendly local web UI

    All processing happens on *your* machine. Nothing is uploaded or sent anywhere.

    **Limitations (transparent)**: PE detection is heuristic and works on the majority of modern justification books but isn't perfect on every page or older formats. Funding dollar amounts are not yet parsed (future enhancement). Direct POCs are almost never in these PDFs — the tool's strength is surfacing the *right programs to chase* and giving you ammunition for research.

    Customize the keyword list heavily for your shop. The more specific, the better the targeting.

    Good luck landing those conversations and contracts. If you extend the tool (semantic search, funding extraction, CRM export, etc.), consider sharing back with the community.
    """)

    st.caption("v1.0 • May 2026 • For legitimate business development use only • Public data only")

# Footer
st.divider()
st.caption("Run locally with `streamlit run app.py` after `pip install -r requirements.txt`. All data stays on your machine.")