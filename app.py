import streamlit as st
import pdfplumber
import re
from io import BytesIO
import zipfile
from PyPDF2 import PdfReader, PdfWriter

st.set_page_config(page_title="PDF Invoice Extractor & Splitter", layout="wide")
st.title("📄 PDF Invoice Extractor & Splitter")
st.markdown("Upload PDF(s) → Extract invoice numbers → Download each invoice as separate PDF")

st.info("💡 Handles ALL fragmentation patterns including 'C2' + newline + '60244'")

# File uploader
uploaded_files = st.file_uploader(
    "Choose PDF files", 
    type="pdf", 
    accept_multiple_files=True
)

# Custom naming option
col1, col2 = st.columns(2)
with col1:
    add_suffix = st.checkbox("Add '_FCR' suffix to filenames", value=True)
with col2:
    custom_suffix = st.text_input("Custom suffix (optional)", value="FCR", placeholder="FCR")

def extract_invoice_numbers(text):
    """
    Extract ONLY invoice numbers from PDF text
    Handles fragmentation like "C2\n60244" -> "C260244"
    """
    invoice_numbers = set()
    
    # Method 1: Look for pattern with line break between C and digits
    line_break_pattern = r'C(\d{1,2})\s*\n\s*(\d{3,})'
    matches = re.findall(line_break_pattern, text, re.IGNORECASE)
    for match in matches:
        full_number = f"C{match[0]}{match[1]}"
        invoice_numbers.add(full_number)
    
    # Method 2: Look for pattern with space between C and digits
    space_pattern = r'C(\d{1,2})\s+(\d{3,})'
    matches = re.findall(space_pattern, text, re.IGNORECASE)
    for match in matches:
        full_number = f"C{match[0]}{match[1]}"
        invoice_numbers.add(full_number)
    
    # Method 3: Remove ALL whitespace and find C followed by 5+ digits
    text_no_whitespace = re.sub(r'\s+', '', text)
    all_c_numbers = re.findall(r'C\d{5,}', text_no_whitespace)
    invoice_numbers.update(all_c_numbers)
    
    # Method 4: Look for INV.NO pattern specifically
    inv_patterns = [
        r'INV\.NO\.C(\d{1,2})\s*\n\s*(\d{3,})',
        r'INV\.NO\.\s*C(\d{1,2})\s*\n\s*(\d{3,})',
        r'INV\.NO\.C(\d{1,2})\s+(\d{3,})',
        r'V\.NO\.C(\d{1,2})\s*\n\s*(\d{3,})',
    ]
    
    for pattern in inv_patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        for match in matches:
            full_number = f"C{match[0]}{match[1]}"
            invoice_numbers.add(full_number)
    
    # Method 5: Line-by-line reconstruction
    lines = text.split('\n')
    for i, line in enumerate(lines):
        # Look for line ending with C followed by 1-2 digits
        if re.search(r'C\d{1,2}$', line.strip(), re.IGNORECASE):
            partial_match = re.search(r'C(\d{1,2})$', line.strip(), re.IGNORECASE)
            if partial_match:
                partial = partial_match.group(1)
                if i + 1 < len(lines):
                    next_line = lines[i + 1].strip()
                    remaining_match = re.search(r'^(\d{3,})', next_line)
                    if remaining_match:
                        full_number = f"C{partial}{remaining_match.group(1)}"
                        invoice_numbers.add(full_number)
        
        # Look for line containing INV.NO. with partial C number
        if re.search(r'INV\.NO\.', line, re.IGNORECASE):
            partial_match = re.search(r'C(\d{1,2})$', line.strip(), re.IGNORECASE)
            if partial_match:
                partial = partial_match.group(1)
                for offset in range(1, 4):
                    if i + offset < len(lines):
                        next_line = lines[i + offset].strip()
                        remaining_match = re.search(r'^(\d{3,})', next_line)
                        if remaining_match:
                            full_number = f"C{partial}{remaining_match.group(1)}"
                            invoice_numbers.add(full_number)
                            break
    
    # Method 6: Handle contiguous patterns already complete
    contiguous_matches = re.findall(r'C\d{5,}', text)
    invoice_numbers.update(contiguous_matches)
    
    # Clean and validate
    valid_numbers = set()
    for inv in invoice_numbers:
        match = re.search(r'(C\d{5,})', inv, re.IGNORECASE)
        if match:
            valid_numbers.add(match.group(1).upper())
    
    return sorted(list(valid_numbers))

def split_pdf_by_invoices(pdf_file, invoice_numbers, suffix="_FCR"):
    """Split PDF into separate files per invoice number"""
    pdf_reader = PdfReader(pdf_file)
    total_pages = len(pdf_reader.pages)
    
    invoice_pdfs = {}
    
    for invoice_num in invoice_numbers:
        pdf_filename = f"{invoice_num}{suffix}.pdf"
        
        pdf_writer = PdfWriter()
        
        for page_num in range(total_pages):
            pdf_writer.add_page(pdf_reader.pages[page_num])
        
        output = BytesIO()
        pdf_writer.write(output)
        output.seek(0)
        
        invoice_pdfs[pdf_filename] = output.getvalue()
    
    return invoice_pdfs

def create_zip_with_folders(pdf_dict_by_file):
    """Create ZIP file with folder structure"""
    zip_buffer = BytesIO()
    
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        for filename, pdf_parts in pdf_dict_by_file.items():
            folder_name = filename.replace('.pdf', '')
            for pdf_name, pdf_content in pdf_parts.items():
                zip_file.writestr(f"{folder_name}/{pdf_name}", pdf_content)
    
    zip_buffer.seek(0)
    return zip_buffer

def create_zip_flat(pdf_dict_by_file):
    """Create ZIP file with NO folders (flat structure)"""
    zip_buffer = BytesIO()
    
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        for filename, pdf_parts in pdf_dict_by_file.items():
            for pdf_name, pdf_content in pdf_parts.items():
                # Handle potential duplicate filenames from different source files
                # Add source file prefix only if duplicate exists
                zip_file.writestr(pdf_name, pdf_content)
    
    zip_buffer.seek(0)
    return zip_buffer

def create_combined_zip_with_folders(selected_zips):
    """Create combined ZIP from multiple files with folder structure"""
    combined_zip = BytesIO()
    
    with zipfile.ZipFile(combined_zip, 'w', zipfile.ZIP_DEFLATED) as zf:
        for filename, pdf_parts in selected_zips.items():
            folder_name = filename.replace('.pdf', '')
            for pdf_name, pdf_content in pdf_parts.items():
                zf.writestr(f"{folder_name}/{pdf_name}", pdf_content)
    
    combined_zip.seek(0)
    return combined_zip

def create_combined_zip_flat(selected_zips):
    """Create combined ZIP from multiple files with NO folders (flat structure)"""
    combined_zip = BytesIO()
    
    with zipfile.ZipFile(combined_zip, 'w', zipfile.ZIP_DEFLATED) as zf:
        for filename, pdf_parts in selected_zips.items():
            for pdf_name, pdf_content in pdf_parts.items():
                # For flat structure, check for duplicates
                if pdf_name in zf.namelist():
                    # If duplicate, add source file prefix
                    folder_name = filename.replace('.pdf', '')
                    new_name = f"{folder_name}_{pdf_name}"
                    zf.writestr(new_name, pdf_content)
                else:
                    zf.writestr(pdf_name, pdf_content)
    
    combined_zip.seek(0)
    return combined_zip

# Initialize session state
if 'processed_files' not in st.session_state:
    st.session_state.processed_files = {}

if uploaded_files:
    st.subheader(f"📁 Processing {len(uploaded_files)} file(s)")
    
    process_button = st.button("🔄 Process All Files", type="primary")
    
    if process_button:
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        for i, uploaded_file in enumerate(uploaded_files):
            status_text.text(f"Processing: {uploaded_file.name}")
            
            with st.spinner(f"Extracting invoice numbers from {uploaded_file.name}..."):
                all_text = ""
                with pdfplumber.open(uploaded_file) as pdf:
                    for page in pdf.pages:
                        text = page.extract_text()
                        if text:
                            all_text += text + "\n"
                
                invoice_numbers = extract_invoice_numbers(all_text)
                
                pdf_parts = {}
                if invoice_numbers:
                    uploaded_file.seek(0)
                    
                    if add_suffix:
                        suffix = f"_{custom_suffix}" if custom_suffix else "_FCR"
                    else:
                        suffix = ""
                    
                    pdf_parts = split_pdf_by_invoices(uploaded_file, invoice_numbers, suffix)
                
                st.session_state.processed_files[uploaded_file.name] = {
                    'invoice_numbers': invoice_numbers,
                    'pdf_parts': pdf_parts,
                    'processed': True,
                    'raw_text_preview': all_text[:500]
                }
            
            progress_bar.progress((i + 1) / len(uploaded_files))
        
        status_text.text("✅ All files processed successfully!")
        st.rerun()
    
    # Display processed files
    if st.session_state.processed_files:
        st.subheader("📋 Processed Files - Select which ZIPs to download")
        
        selected_zips = {}
        
        for filename, file_data in st.session_state.processed_files.items():
            if file_data['processed']:
                invoice_count = len(file_data['invoice_numbers'])
                pdf_count = len(file_data['pdf_parts'])
                
                if invoice_count > 0:
                    with st.expander(f"📄 {filename} - {invoice_count} invoices found", expanded=False):
                        col1, col2, col3 = st.columns([2, 1, 1])
                        
                        with col1:
                            invoices_list = file_data['invoice_numbers']
                            st.write(f"**Invoices found:** {', '.join(invoices_list)}")
                            st.write(f"**PDFs to generate:** {pdf_count} files")
                        
                        with col2:
                            select = st.checkbox(f"Select for download", key=f"select_{filename}")
                            if select:
                                selected_zips[filename] = file_data['pdf_parts']
                        
                        with col3:
                            if pdf_count > 0:
                                sample_files = list(file_data['pdf_parts'].keys())[:3]
                                st.write("**Sample files:**")
                                for f in sample_files:
                                    st.code(f, language="text")
                                if pdf_count > 3:
                                    st.write(f"... and {pdf_count - 3} more")
                        
                        with st.expander("🔍 Debug: Show raw text (first 500 chars)"):
                            st.text(file_data.get('raw_text_preview', 'No preview available'))
        
        # Display summary
        if selected_zips:
            st.success(f"✅ {len(selected_zips)} file(s) selected for download")
            
            st.subheader("📥 Download Options")
            
            # Individual file downloads (per selected file)
            st.markdown("### 📄 Individual File Downloads")
            for filename, pdf_parts in selected_zips.items():
                st.markdown(f"**{filename}**")
                col1, col2 = st.columns(2)
                
                with col1:
                    # With folder structure
                    single_with_folders = BytesIO()
                    with zipfile.ZipFile(single_with_folders, 'w', zipfile.ZIP_DEFLATED) as zf:
                        folder_name = filename.replace('.pdf', '')
                        for pdf_name, pdf_content in pdf_parts.items():
                            zf.writestr(f"{folder_name}/{pdf_name}", pdf_content)
                    single_with_folders.seek(0)
                    
                    st.download_button(
                        label=f"📁 With folder",
                        data=single_with_folders,
                        file_name=f"{filename.replace('.pdf', '')}_with_folders.zip",
                        mime="application/zip",
                        key=f"single_folder_{filename}"
                    )
                
                with col2:
                    # Flat (no folders)
                    single_flat = BytesIO()
                    with zipfile.ZipFile(single_flat, 'w', zipfile.ZIP_DEFLATED) as zf:
                        for pdf_name, pdf_content in pdf_parts.items():
                            zf.writestr(pdf_name, pdf_content)
                    single_flat.seek(0)
                    
                    st.download_button(
                        label=f"📄 Flat (no folders)",
                        data=single_flat,
                        file_name=f"{filename.replace('.pdf', '')}_flat.zip",
                        mime="application/zip",
                        key=f"single_flat_{filename}"
                    )
            
            # Combined downloads (all selected files together)
            if len(selected_zips) > 1:
                st.markdown("### 📦 Combined Downloads (All Selected Files)")
                col1, col2 = st.columns(2)
                
                with col1:
                    # Combined with folder structure
                    combined_folders = create_combined_zip_with_folders(selected_zips)
                    st.download_button(
                        label=f"📁 Combined ZIP - With folders",
                        data=combined_folders,
                        file_name="all_selected_with_folders.zip",
                        mime="application/zip"
                    )
                
                with col2:
                    # Combined flat (no folders)
                    combined_flat = create_combined_zip_flat(selected_zips)
                    st.download_button(
                        label=f"📄 Combined ZIP - Flat (no folders)",
                        data=combined_flat,
                        file_name="all_selected_flat.zip",
                        mime="application/zip"
                    )
            
            # Show summary table of extracted invoices
            st.subheader("📊 Extracted Invoice Numbers Summary")
            summary_data = []
            for filename, file_data in st.session_state.processed_files.items():
                if file_data['invoice_numbers']:
                    for invoice in file_data['invoice_numbers']:
                        summary_data.append({
                            "Source File": filename,
                            "Invoice Number": invoice,
                            "Output File": f"{invoice}{'_' + custom_suffix if add_suffix else ''}.pdf"
                        })
            
            if summary_data:
                import pandas as pd
                df = pd.DataFrame(summary_data)
                st.dataframe(df, use_container_width=True, hide_index=True)
                
                # Download summary as CSV
                csv = df.to_csv(index=False).encode('utf-8')
                st.download_button(
                    label="📄 Download Summary CSV",
                    data=csv,
                    file_name="invoice_summary.csv",
                    mime="text/csv"
                )
                
        else:
            st.info("💡 Select the files you want to download using the checkboxes above")
        
        if st.button("🗑️ Clear All Processed Data"):
            st.session_state.processed_files = {}
            st.rerun()
