import streamlit as st
import pandas as pd
import pdfplumber
import collections

# --- 輔助函數 ---
def normalize_text(cell_content):
    """
    標準化從 pdfplumber 提取的單元格內容。
    處理 None 值、pdfplumber 的 Text 物件和普通字串。
    """
    if cell_content is None:
        return ""

    if hasattr(cell_content, 'text'):
        return str(cell_content.text).strip()
    elif isinstance(cell_content, str):
        return cell_content.strip()
    else:
        return str(cell_content).strip()

def make_unique_columns(columns_list):
    """
    將列表中的欄位名稱轉換為唯一的名稱，處理重複和空字串。
    如果遇到重複或空字串，會添加後綴 (例如 'Column_1', '欄位_2')。
    """
    seen = collections.defaultdict(int)
    unique_columns = []
    for col in columns_list:
        original_col = col if col else f"Column_{len(unique_columns) + 1}"
        
        name = original_col
        if seen[name] > 0:
            name = f"{original_col}_{seen[original_col]}"
        while name in unique_columns:
             seen[original_col] += 1
             name = f"{original_col}_{seen[original_col]}"
        
        unique_columns.append(name)
        seen[original_col] += 1
    return unique_columns

def calculate_total_credits(df_list):
    """
    從提取的 DataFrames 列表中計算總學分。
    尋找包含 '學分' 或 '學分(GPA)' 類似字樣的欄位進行加總。
    """
    total_credits = 0.0
    
    st.subheader("學分計算分析")

    # 定義可能的學分欄位名稱關鍵字，請根據實際偵測到的欄位名稱調整
    # 增加更多可能的學分欄位名稱變體
    credit_column_keywords = ["學分", "學分數", "學分(GPA)", "學 分"] #

    for df_idx, df in enumerate(df_list):
        st.write(f"--- 分析表格 {df_idx + 1} ---")
        st.write(f"偵測到的欄位名稱: `{list(df.columns)}`") # 輸出偵測到的所有欄位名稱

        found_credit_column = None
        for col in df.columns:
            # 更加激進的清理，移除所有非中文/英文/數字的字元，只保留核心詞
            cleaned_col = "".join(char for char in col if '\u4e00' <= char <= '\u9fa5' or 'a' <= char <= 'z' or 'A' <= char <= 'Z' or '0' <= char <= '9').strip()
            
            # 檢查是否包含關鍵字
            if any(keyword in cleaned_col for keyword in credit_column_keywords):
                found_credit_column = col
                break
        
        if found_credit_column:
            st.info(f"從表格 {df_idx + 1} (原始欄位: '{found_credit_column}') 偵測到學分數據。")
            try:
                # 嘗試將學分欄位轉換為數值，非數值設為 NaN，然後填充 0
                # 確保只有數字和可以轉換的字元被處理，並排除像"通過"這樣的成績
                # 邱旭廷的PDF顯示學分欄位有"抵免"
                credits = pd.to_numeric(df[found_credit_column], errors='coerce').fillna(0) 
                
                # 篩選掉 GPA 列中的"抵免"、"通過"等非數字字串，只加總有效的數字學分
                # 這裡假設學分不會是負數，且0學分可能是體育課等
                valid_credits = credits[credits >= 0] # 包含 0 學分 (例如體育課)
                
                current_table_credits = valid_credits.sum()
                total_credits += current_table_credits
                st.write(f"表格 {df_idx + 1} 的學分總計: **{current_table_credits:.2f}**")
                
            except Exception as e:
                st.warning(f"表格 {df_idx + 1} 的學分欄位 '{found_credit_column}' 轉換為數值時發生錯誤: `{e}`")
                st.warning("該表格的學分可能無法計入總數。請檢查學分欄位數據是否為純數字。")
        else:
            st.info(f"表格 {df_idx + 1} 未偵測到明確的學分欄位。檢查欄位：`{list(df.columns)}`。不計入總學分。")
            
    return total_credits

def process_pdf_file(uploaded_file):
    """
    使用 pdfplumber 處理上傳的 PDF 檔案，提取表格。
    """
    all_grades_data = []

    try:
        with pdfplumber.open(uploaded_file) as pdf:
            st.write(f"正在處理檔案: **{uploaded_file.name}**")
            num_pages = len(pdf.pages)
            st.info(f"PDF 總頁數: **{num_pages}**")

            for page_num, page in enumerate(pdf.pages):
                st.subheader(f"頁面 {page_num + 1}")

                table_settings = {
                    "vertical_strategy": "lines",
                    "horizontal_strategy": "lines",
                    "snap_tolerance": 3,
                    "join_tolerance": 3,
                    "edge_min_length": 3,
                    "text_tolerance": 1,
                }

                try:
                    tables = page.extract_tables(table_settings)

                    if not tables:
                        st.warning(f"頁面 **{page_num + 1}** 未偵測到表格。這可能是由於 PDF 格式複雜或表格提取設定不適用。")
                        continue

                    for table_idx, table in enumerate(tables):
                        st.markdown(f"**頁面 {page_num + 1} 的表格 {table_idx + 1}**")
                        
                        processed_table = []
                        for row in table:
                            normalized_row = [normalize_text(cell) for cell in row]
                            processed_table.append(normalized_row)
                        
                        if not processed_table:
                            st.info(f"表格 **{table_idx + 1}** 提取後為空。")
                            continue

                        # 假設第一行是標題行，但確保有足夠的行
                        if len(processed_table) > 0:
                            header_row = processed_table[0]
                            data_rows = processed_table[1:]
                        else:
                            header_row = [] # 如果表格是空的，標題也為空
                            data_rows = []

                        unique_columns = make_unique_columns(header_row)

                        if data_rows:
                            num_columns_header = len(unique_columns)
                            cleaned_data_rows = []
                            for row in data_rows:
                                if len(row) > num_columns_header:
                                    cleaned_data_rows.append(row[:num_columns_header])
                                elif len(row) < num_columns_header:
