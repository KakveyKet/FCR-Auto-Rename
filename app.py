import streamlit as st
import pdfplumber
import re
from io import BytesIO
import zipfile
from PyPDF2 import PdfReader, PdfWriter

st.set_page_config(page_title="PDF Invoice Extractor & Splitter", layout="wide")
st.title("📄 PDF Invoice Extractor & Splitter")
st.markdown("Upload PDF(s) → Extract invoice numbers → Download each invoice as separate PDF")

st.info("💡 Handles fragmentation: 'C26149' + newline + '0' → 'C261490'")
st.info("🎯 ONLY extracts complete invoice numbers (C26-C29, 6-7 total characters)")

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

def is_valid_invoice_range(invoice_num):
    """Check if invoice number starts with C26, C27, C28, or C29"""
    match = re.search(r'C(\d{2})', invoice_num.upper())
    if match:
        first_two = int(match.group(1))
        if first_two in [26, 27, 28, 29]:
            return 6 <= len(invoice_num) <= 7
    return False

def extract_invoice_numbers(text):
    """Extract ONLY invoice numbers from PDF text"""
    invoice_numbers = set()
    
    # Handle INV.NO.Cxxxxx with number on next line
    inv_split_pattern = r'INV\.NO\.C(\d+)\s*\n\s*(\d+)'
    matches = re.findall(inv_split_pattern, text, re.IGNORECASE)
    for match in matches:
        full_number = f"C{match[0]}{match[1]}"
        if 6 <= len(full_number) <= 7 and is_valid_invoice_range(full_number):
            invoice_numbers.add(full_number)
    
    # Look for pattern with line break
    line_break_pattern = r'C(\d{3,5})\s*\n\s*(\d{1,3})'
    matches = re.findall(line_break_pattern, text, re.IGNORECASE)
    for match in matches:
        full_number = f"C{match[0]}{match[1]}"
        if 6 <= len(full_number) <= 7 and is_valid_invoice_range(full_number):
            invoice_numbers.add(full_number)
    
    # Remove ALL whitespace and find C followed by 6-7 total chars
    text_no_whitespace = re.sub(r'\s+', '', text)
    all_c_numbers = re.findall(r'C\d{5,6}', text_no_whitespace)
    for num in all_c_numbers:
        if len(num) == 6 or len(num) == 7:
            if is_valid_invoice_range(num):
                invoice_numbers.add(num)
    
    # Line-by-line reconstruction
    lines = text.split('\n')
    for i, line in enumerate(lines):
        if re.search(r'INV\.NO\.C', line, re.IGNORECASE):
            c_match = re.search(r'C(\d+)$', line.strip(), re.IGNORECASE)
            if c_match:
                partial = c_match.group(1)
                for offset in range(1, 4):
                    if i + offset < len(lines):
                        next_line = lines[i + offset].strip()
                        remaining_match = re.search(r'^(\d+)', next_line)
                        if remaining_match:
                            full_number = f"C{partial}{remaining_match.group(1)}"
                            if 6 <= len(full_number) <= 7 and is_valid_invoice_range(full_number):
                                invoice_numbers.add(full_number)
                            break
    
    # Direct pattern for Cxxxxx followed by newline then digits
    direct_split = r'C(\d{5,6})\s*\n\s*(\d+)'
    matches = re.findall(direct_split, text, re.IGNORECASE)
    for match in matches:
        full_number = f"C{match[0]}{match[1]}"
        if len(full_number) <= 7 and is_valid_invoice_range(full_number):
            invoice_numbers.add(full_number)
    
    # Clean and validate - remove incomplete numbers
    valid_numbers = set()
    for inv in invoice_numbers:
        if 6 <= len(inv) <= 7 and is_valid_invoice_range(inv):
            valid_numbers.add(inv.upper())
    
    # Remove prefixes (C26149 is prefix of C261490)
    final_numbers = set()
    numbers_list = list(valid_numbers)
    for num in numbers_list:
        is_prefix = False
        for other in numbers_list:
            if num != other and other.startswith(num):
                is_prefix = True
                break
        if not is_prefix:
            final_numbers.add(num)
    
    return sorted(list(final_numbers))

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

def create_zip_flat(pdf_parts):
    """Create ZIP file with flat structure (no folders)"""
    zip_buffer = BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        for filename, content in pdf_parts.items():
            zip_file.writestr(filename, content)
    zip_buffer.seek(0)
    return zip_buffer

def create_zip_with_folders(selected_files_data):
    """Create ZIP file with folder structure (each file in its own folder)"""
    zip_buffer = BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        for filename, file_data in selected_files_data.items():
            folder_name = filename.replace('.pdf', '')
            for pdf_name, pdf_content in file_data['pdf_parts'].items():
                zip_file.writestr(f"{folder_name}/{pdf_name}", pdf_content)
    zip_buffer.seek(0)
    return zip_buffer

# Initialize session state
if 'processed_files' not in st.session_state:
    st.session_state.processed_files = {}
if 'selected_files' not in st.session_state:
    st.session_state.selected_files = []

if uploaded_files:
    st.subheader(f"📁 {len(uploaded_files)} file(s) uploaded")
    
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
        st.session_state.selected_files = []
        st.rerun()
    
    # Display processed files with selection
    if st.session_state.processed_files:
        st.subheader("📋 Select Files to Download")
        
        # Create list of filenames that have invoices
        file_options = []
        file_info = {}
        
        for filename, file_data in st.session_state.processed_files.items():
            if file_data['processed'] and len(file_data['invoice_numbers']) > 0:
                invoice_list = ', '.join(file_data['invoice_numbers'])
                display_text = f"{filename} | Invoices: {invoice_list}"
                file_options.append(display_text)
                file_info[display_text] = {
                    'filename': filename,
                    'data': file_data
                }
        
        if file_options:
            # Use multiselect for selection
            selected_display = st.multiselect(
                "Select files to download:",
                options=file_options,
                default=None,
                help="Click to select files, or use buttons below"
            )
            
            # Update selected_files based on selections
            current_selected = [file_info[opt]['filename'] for opt in selected_display]
            st.session_state.selected_files = current_selected
            
            # Selection control buttons
            col1, col2, col3 = st.columns(3)
            
            with col1:
                if st.button("✅ Select All", use_container_width=True):
                    all_selected = [opt for opt in file_options]
                    st.session_state.selected_files = [file_info[opt]['filename'] for opt in all_selected]
                    st.rerun()
            
            with col2:
                if st.button("❌ Deselect All", use_container_width=True):
                    st.session_state.selected_files = []
                    st.rerun()
            
            with col3:
                selected_count = len(st.session_state.selected_files)
                st.markdown(f"**Selected: {selected_count} file(s)**")
            
            st.markdown("---")
            
            # Show selected files with their invoices
            if st.session_state.selected_files:
                st.subheader(f"📌 Selected Files ({len(st.session_state.selected_files)})")
                for filename in st.session_state.selected_files:
                    if filename in st.session_state.processed_files:
                        file_data = st.session_state.processed_files[filename]
                        invoices_list = ', '.join(file_data['invoice_numbers'])
                        st.markdown(f"- **{filename}** → {invoices_list}")
                
                st.markdown("---")
                st.subheader("📥 Download Options")
                
                # Prepare selected files data
                selected_files_data = {}
                for filename in st.session_state.selected_files:
                    if filename in st.session_state.processed_files:
                        selected_files_data[filename] = st.session_state.processed_files[filename]
                
                # Count total PDFs
                total_pdfs = sum(len(data['pdf_parts']) for data in selected_files_data.values())
                
                # Download options - Flat and With Folders
                col1, col2 = st.columns(2)
                
                with col1:
                    # Flat ZIP (no folders)
                    flat_zip = create_zip_flat({})
                    flat_pdfs = {}
                    for filename, file_data in selected_files_data.items():
                        for pdf_name, pdf_content in file_data['pdf_parts'].items():
                            flat_pdfs[f"{filename.replace('.pdf', '')}_{pdf_name}"] = pdf_content
                    
                    if flat_pdfs:
                        flat_zip = create_zip_flat(flat_pdfs)
                        st.download_button(
                            label=f"📄 Flat ZIP ({total_pdfs} files - no folders)",
                            data=flat_zip,
                            file_name="selected_invoices_flat.zip",
                            mime="application/zip",
                            key="flat_download",
                            use_container_width=True
                        )
                        st.caption("All PDFs directly in ZIP root")
                
                with col2:
                    # With Folders ZIP
                    if selected_files_data:
                        folders_zip = create_zip_with_folders(selected_files_data)
                        st.download_button(
                            label=f"📁 Folders ZIP ({total_pdfs} files - with folders)",
                            data=folders_zip,
                            file_name="selected_invoices_with_folders.zip",
                            mime="application/zip",
                            key="folders_download",
                            use_container_width=True
                        )
                        st.caption("Each file in its own folder")
            
            # Display each file details
            st.markdown("---")
            st.subheader("📄 Available Files")
            for filename, file_data in st.session_state.processed_files.items():
                if file_data['processed'] and len(file_data['invoice_numbers']) > 0:
                    invoice_count = len(file_data['invoice_numbers'])
                    pdf_count = len(file_data['pdf_parts'])
                    invoices_list = ', '.join(file_data['invoice_numbers'])
                    
                    with st.expander(f"📄 {filename}"):
                        st.markdown(f"**Invoices found:** {invoices_list}")
                        st.markdown(f"**PDFs to generate:** {pdf_count} files")
                        
                        # Preview PDF names
                        sample_files = list(file_data['pdf_parts'].keys())[:5]
                        st.markdown("**Sample output files:**")
                        for f in sample_files:
                            st.code(f, language="text")
                        if pdf_count > 5:
                            st.caption(f"... and {pdf_count - 5} more")
        else:
            st.warning("No invoices found in any uploaded file")
        
        # Clear data button
        if st.button("🗑️ Clear All Data", type="secondary"):
            st.session_state.processed_files = {}
            st.session_state.selected_files = []
            st.rerun()
