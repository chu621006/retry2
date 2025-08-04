import streamlit as st
import pandas as pd
import pdfplumber
import collections
import re 

# --- 輔助函數 ---
def normalize_text(cell_content):
    """
    標準化從 pdfplumber 提取的單元格內容。
    處理 None 值、pdfplumber 的 Text 物件和普通字串。
    將多個空白字元（包括換行）替換為單個空格，並去除兩端空白。
    """
    if cell_content is None:
        return ""

    text = ""
    if hasattr(cell_content, 'text'):
        text = str(cell_content.text)
    elif isinstance(cell_content, str):
        text = cell_content
    else:
        text = str(cell_content)
    
    return re.sub(r'\s+', ' ', text).strip()

def make_unique_columns(columns_list):
    """
    將列表中的欄位名稱轉換為唯一的名稱，處理重複和空字串。
    如果遇到重複或空字串，會添加後綴 (例如 'Column_1', '欄位_2')。
    """
    seen = collections.defaultdict(int)
    unique_columns = []
    for col in columns_list:
        original_col_cleaned = normalize_text(col)
        
        if not original_col_cleaned or len(original_col_cleaned) < 2: 
            name_base = "Column"
            current_idx = 1
            while f"{name_base}_{current_idx}" in unique_columns:
                current_idx += 1
            name = f"{name_base}_{current_idx}"
        else:
            name = original_col_cleaned
        
        final_name = name
        counter = seen[name]
        while final_name in unique_columns:
            counter += 1
            final_name = f"{name}_{counter}" if counter > 0 else name
        
        unique_columns.append(final_name)
        seen[name] = counter

    return unique_columns

def calculate_total_credits(df_list):
    """
    從提取的 DataFrames 列表中計算總學分。
    尋找包含 '學分' 或 '學分(GPA)' 類似字樣的欄位進行加總。
    返回總學分和計算學分的科目列表。
    """
    total_credits = 0.0
    calculated_courses = [] # 用於存放計算了學分的科目名稱和學分

    st.subheader("學分計算分析")

    credit_column_keywords = ["學分", "學分數", "學分(GPA)", "學 分", "Credits", "Credit"] 
    subject_column_keywords = ["科目名稱", "課程名稱", "Course Name", "Subject Name", "科目"] # 新增科目名稱關鍵字

    credit_pattern = re.compile(r'(\d+(\.\d+)?)') 

    for df_idx, df in enumerate(df_list):
        st.write(f"--- 分析表格 {df_idx + 1} ---")
        st.write(f"偵測到的原始欄位名稱: `{list(df.columns)}`") 
        
        found_credit_column = None
        found_subject_column = None # 偵測科目名稱欄位
        
        # 步驟 1: 優先匹配明確的學分和科目關鍵字
        for col in df.columns:
            cleaned_col_for_match = "".join(char for char in normalize_text(col) if '\u4e00' <= char <= '\u9fa5' or 'a' <= char <= 'z' or 'A' <= char <= 'Z' or '0' <= char <= '9').strip()
            
            if any(keyword in cleaned_col_for_match for keyword in credit_column_keywords):
                found_credit_column = col 
            if any(keyword in cleaned_col_for_match for keyword in subject_column_keywords):
                found_subject_column = col
            
            if found_credit_column and found_subject_column:
                break # 兩個都找到就停止

        # 步驟 2: 如果沒有明確匹配，嘗試從通用名稱 (Column_X) 中猜測學分和科目欄位
        if not found_credit_column or not found_subject_column:
            potential_credit_columns = []
            potential_subject_columns = []

            for col in df.columns:
                is_general_col = re.match(r"Column_\d+", col) or len(col.strip()) < 3
                
                # 檢查是否為潛在學分欄位
                sample_data = df[col].head(10).apply(normalize_text).tolist()
                numeric_like_count = 0
                total_sample_count = len(sample_data)
                
                for item_str in sample_data:
                    if item_str == "通過" or item_str == "抵免" or item_str.lower() in ["pass", "exempt"]:
                        numeric_like_count += 1
                    else:
                        matches = credit_pattern.findall(item_str)
                        if matches:
                            try:
                                val = float(matches[-1][0])
                                if 0.0 <= val <= 10.0: 
                                    numeric_like_count += 1
                            except ValueError:
                                pass
                
                if total_sample_count > 0 and numeric_like_count / total_sample_count >= 0.6:
                    potential_credit_columns.append(col)
                
                # 檢查是否為潛在科目名稱欄位 (若包含中文且非純數字)
                if is_general_col:
                    subject_like_count = 0
                    for item_str in sample_data:
                        if len(item_str) > 3 and not item_str.isdigit() and not re.match(r'^\d+(\.\d+)?$', item_str): # 至少3個字，不是純數字
                            subject_like_count += 1
                    if total_sample_count > 0 and subject_like_count / total_sample_count >= 0.7: # 更高門檻
                        potential_subject_columns.append(col)

            # 步驟 3: 根據推斷結果確定學分和科目欄位
            if not found_credit_column and potential_credit_columns:
                best_credit_candidate = None
                if found_subject_column: # 如果已找到科目名稱，則選擇其右側的學分欄位
                    subject_col_idx = df.columns.get_loc(found_subject_column)
                    min_dist = float('inf')
                    for p_col in potential_credit_columns:
                        p_col_idx = df.columns.get_loc(p_col)
                        if p_col_idx > subject_col_idx and (p_col_idx - subject_col_idx) < min_dist:
                            min_dist = p_col_idx - subject_col_idx
                            best_credit_candidate = p_col
                
                if not best_credit_candidate and potential_credit_columns: # 否則選擇第一個潛在學分欄位
                    best_credit_candidate = potential_credit_columns[0]
                
                found_credit_column = best_credit_candidate

            if not found_subject_column and potential_subject_columns:
                found_subject_column = potential_subject_columns[0] # 簡單選擇第一個潛在科目欄位

        if found_credit_column:
            st.info(f"從表格 {df_idx + 1} 偵測到學分欄位: '{found_credit_column}'。")
            if found_subject_column:
                st.info(f"從表格 {df_idx + 1} 偵測到科目名稱欄位: '{found_subject_column}'。")
            else:
                st.warning(f"表格 {df_idx + 1} 未偵測到明確的科目名稱欄位。科目名稱可能無法準確記錄。")

            try:
                current_table_credits = 0.0
                for row_idx, row in df.iterrows():
                    item_str = normalize_text(row[found_credit_column])
                    
                    credit_val = 0.0
                    if item_str == "通過" or item_str == "抵免" or item_str.lower() in ["pass", "exempt"]:
                        credit_val = 0.0
                    else:
                        matches = credit_pattern.findall(item_str)
                        if matches:
                            try:
                                val = float(matches[-1][0])
                                if 0.0 <= val <= 10.0: 
                                    credit_val = val
                                else:
                                    credit_val = 0.0 
                            except ValueError:
                                credit_val = 0.0
                        else:
                            credit_val = 0.0 
                    
                    if credit_val > 0: # 只記錄有學分的科目
                        current_table_credits += credit_val
                        
                        course_name = "未知科目"
                        if found_subject_column and found_subject_column in row:
                            course_name = normalize_text(row[found_subject_column])
                        
                        calculated_courses.append({"科目名稱": course_name, "學分": credit_val, "來源表格": df_idx + 1})

                total_credits += current_table_credits
                st.write(f"表格 {df_idx + 1} 的學分總計: **{current_table_credits:.2f}**")
                
            except Exception as e:
                st.warning(f"表格 {df_idx + 1} 的學分欄位 '{found_credit_column}' 轉換為數值時發生錯誤: `{e}`")
                st.warning("該表格的學分可能無法計入總數。請檢查學分欄位數據是否為純數字或可提取數字。")
        else:
            st.info(f"表格 {df_idx + 1} 未偵測到明確的學分欄位。檢查欄位：`{list(df.columns)}`。不計入總學分。")
            
    return total_credits, calculated_courses

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
                
                current_page = page 

                try:
                    tables = current_page.extract_tables(table_settings)

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

                        if len(processed_table) > 0:
                            header_row = processed_table[0]
                            data_rows = processed_table[1:]
                        else:
                            header_row = []
                            data_rows = []

                        unique_columns = make_unique_columns(header_row)

                        if data_rows:
                            num_columns_header = len(unique_columns)
                            cleaned_data_rows = []
                            for row in data_rows:
                                if len(row) > num_columns_header:
                                    cleaned_data_rows.append(row[:num_columns_header])
                                elif len(row) < num_columns_header:
                                    cleaned_data_rows.append(row + [''] * (num_columns_header - len(row)))
                                else:
                                    cleaned_data_rows.append(row)

                            try:
                                df_table = pd.DataFrame(cleaned_data_rows, columns=unique_columns)
                                all_grades_data.append(df_table)
                                # st.dataframe(df_table) # 移除詳細表格輸出
                            except Exception as e_df:
                                st.error(f"頁面 {page_num + 1} 表格 {table_idx + 1} 轉換為 DataFrame 時發生錯誤: `{e_df}`")
                                st.error(f"原始處理後數據範例: {processed_table[:2]} (前兩行)")
                                st.error(f"生成的唯一欄位名稱: {unique_columns}")
                        else:
                            st.info(f"表格 **{table_idx + 1}** 沒有數據行。")

                except Exception as e_table:
                    st.error(f"頁面 **{page_num + 1}** 處理表格時發生錯誤: `{e_table}`")
                    st.warning("這可能是由於 PDF 格式複雜或表格提取設定不適用。請檢查 PDF 結構。")

    except pdfplumber.PDFSyntaxError as e_pdf_syntax:
        st.error(f"處理 PDF 語法時發生錯誤: `{e_pdf_syntax}`。檔案可能已損壞或格式不正確。")
    except Exception as e:
        st.error(f"處理 PDF 檔案時發生一般錯誤: `{e}`")
        st.error("請確認您的 PDF 格式是否為清晰的表格。若問題持續，可能是 PDF 結構較為複雜，需要調整 `pdfplumber` 的表格提取設定。")

    return all_grades_data

# --- Streamlit 應用主體 ---
def main():
    st.set_page_config(page_title="PDF 成績單學分計算工具", layout="wide")
    st.title("📄 PDF 成績單學分計算工具")

    st.write("請上傳您的 PDF 成績單檔案，工具將嘗試提取其中的表格數據並計算總學分。")
    st.write("您也可以輸入目標學分，查看還差多少學分。")

    uploaded_file = st.file_uploader("選擇一個 PDF 檔案", type="pdf")

    if uploaded_file is not None:
        st.success(f"已上傳檔案: **{uploaded_file.name}**")
        with st.spinner("正在處理 PDF，請稍候..."):
            extracted_dfs = process_pdf_file(uploaded_file)

        if extracted_dfs:
            st.success("成功提取所有表格數據！")
            
            total_credits, calculated_courses = calculate_total_credits(extracted_dfs)

            st.markdown("---")
            st.markdown("## 📊 學分計算結果")
            st.markdown(f"**總計學分: <span style='color:green; font-size: 24px;'>{total_credits:.2f}</span>**", unsafe_allow_html=True)
            st.info("請注意：學分計算是基於偵測到的「學分」欄位加總，並排除「抵免」、「通過」等非數字或非正數學分。")

            # 輸入目標學分
            target_credits = st.number_input("輸入您的目標學分 (例如：128)", min_value=0.0, value=128.0, step=1.0)
            
            credit_difference = target_credits - total_credits
            if credit_difference > 0:
                st.warning(f"距離目標學分還差: **{credit_difference:.2f}** 學分")
            elif credit_difference < 0:
                st.success(f"已超越目標學分: **{abs(credit_difference):.2f}** 學分！")
            else:
                st.success("已達到目標學分！")

            st.markdown("---")
            st.markdown("### ✨ 有計算學分的科目列表")
            if calculated_courses:
                # 將科目列表轉換為 DataFrame 以便顯示
                courses_df = pd.DataFrame(calculated_courses)
                st.dataframe(courses_df, height=300) # 限制高度
            else:
                st.info("沒有找到可以計算學分的科目。")

            # 提供下載選項 (僅下載總結數據，而非原始表格)
            # 這裡我們只提供計算出的科目列表下載，如果需要原始表格，可以再加回去
            if calculated_courses:
                csv_data = courses_df.to_csv(index=False, encoding='utf-8-sig')
                st.download_button(
                    label="下載計算學分的科目列表為 CSV",
                    data=csv_data,
                    file_name=f"{uploaded_file.name.replace('.pdf', '')}_calculated_courses.csv",
                    mime="text/csv",
                )
            
        else:
            st.warning("未從 PDF 中提取到任何表格數據。請檢查 PDF 內容或嘗試調整 `pdfplumber` 的表格提取設定。")
    else:
        st.info("請上傳 PDF 檔案以開始處理。")

if __name__ == "__main__":
    main()
