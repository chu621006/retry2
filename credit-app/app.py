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
    # 檢查是否是 pdfplumber 的 Text 物件，它通常有 'text' 屬性
    if hasattr(cell_content, 'text'):
        text = str(cell_content.text)
    elif isinstance(cell_content, str):
        text = cell_content
    else:
        # 對於其他未知類型，嘗試直接轉換為字串
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
        
        # 如果清理後還是空的，或者太短無法識別為有意義的標題，則給予通用名稱
        if not original_col_cleaned or len(original_col_cleaned) < 2: 
            name_base = "Column"
            current_idx = 1
            while f"{name_base}_{current_idx}" in unique_columns:
                current_idx += 1
            name = f"{name_base}_{current_idx}"
        else:
            name = original_col_cleaned
        
        # 處理重複名稱，避免 Column_1, Column_1_1 這種情況
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
    返回總學分和計算學分的科目列表，以及不及格科目列表。
    """
    total_credits = 0.0
    calculated_courses = [] # 用於存放計算了學分的科目名稱和學分
    failed_courses = [] # 用於存放不及格的科目

    # 定義可能的學分欄位名稱關鍵字 (中文和英文)
    credit_column_keywords = ["學分", "學分數", "學分(GPA)", "學 分", "Credits", "Credit"] 
    # 定義可能的科目名稱關鍵字
    subject_column_keywords = ["科目名稱", "課程名稱", "Course Name", "Subject Name", "科目", "課程"] # 增加 '課程'
    # 定義可能的 GPA 欄位名稱關鍵字
    gpa_column_keywords = ["GPA", "成績", "Grade"] # 增加 '成績' 和 'Grade'

    # 用於從可能包含GPA的字符串中提取數字學分，例如 "A 2" -> 2, "3" -> 3
    credit_pattern = re.compile(r'(\d+(\.\d+)?)') 
    # 定義不及格的 GPA 等級 (根據常見的台灣學制，D以下為不及格)
    failing_grades = ["D", "D-", "E", "F", "X", "不通過", "未通過"] # 增加不通過/未通過

    for df_idx, df in enumerate(df_list):
        found_credit_column = None
        found_subject_column = None 
        found_gpa_column = None # 偵測 GPA 欄位
        
        # 步驟 1: 優先匹配明確的學分、科目和 GPA 關鍵字
        for col in df.columns:
            cleaned_col_for_match = "".join(char for char in normalize_text(col) if '\u4e00' <= char <= '\u9fa5' or 'a' <= char <= 'z' or 'A' <= char <= 'Z' or '0' <= char <= '9').strip()
            
            if any(keyword in cleaned_col_for_match for keyword in credit_column_keywords):
                found_credit_column = col 
            if any(keyword in cleaned_col_for_match for keyword in subject_column_keywords):
                found_subject_column = col
            if any(keyword in cleaned_col_for_match for keyword in gpa_column_keywords):
                found_gpa_column = col
            
            # 如果三個都找到了，就可以提前結束循環
            if found_credit_column and found_subject_column and found_gpa_column:
                break 
        
        # 步驟 2: 如果沒有明確匹配，嘗試從通用名稱 (Column_X) 中猜測欄位
        # 為了更準確地猜測科目名稱，我們可以檢查其內容的「漢字密度」或「非數字長度」。
        if not found_credit_column or not found_subject_column or not found_gpa_column:
            potential_credit_columns = []
            potential_subject_columns = []
            potential_gpa_columns = []

            for col_name in df.columns: # 使用 col_name 避免與函數內的 col 變數衝突
                is_general_col = re.match(r"Column_\d+", col_name) or len(normalize_text(col_name).strip()) < 3
                sample_data = df[col_name].head(10).apply(normalize_text).tolist()
                total_sample_count = len(sample_data)

                # 判斷潛在學分欄位
                numeric_like_count = 0
                for item_str in sample_data:
                    if item_str in ["通過", "抵免", "pass", "exempt", "Pass", "Exempt"]: # 兼容大小寫
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
                    potential_credit_columns.append(col_name)

                # 判斷潛在科目名稱欄位 (更智能的判斷)
                subject_like_count = 0
                for item_str in sample_data:
                    # 判斷是否看起來像科目名稱: 包含中文字符，長度通常較長 (>4個字), 且不全是數字或單個字母成績
                    if re.search(r'[\u4e00-\u9fa5]', item_str) and len(item_str) > 4 and not item_str.isdigit() and not re.match(r'^[A-Fa-f][+-]?$', item_str): 
                        subject_like_count += 1
                if total_sample_count > 0 and subject_like_count / total_sample_count >= 0.7: 
                    potential_subject_columns.append(col_name)

                # 判斷潛在 GPA 欄位
                gpa_like_count = 0
                for item_str in sample_data:
                    # 檢查是否是標準的 GPA 字母等級 (A+, B-, C, D, E, F) 或數字分數
                    if re.match(r'^[A-Fa-f][+-]?$', item_str) or re.match(r'^\d+(\.\d+)?$', item_str):
                        gpa_like_count += 1
                if total_sample_count > 0 and gpa_like_count / total_sample_count >= 0.6: 
                    potential_gpa_columns.append(col_name)

            # 步驟 3: 根據推斷結果確定學分、科目和 GPA 欄位
            # 確保優先級：科目名稱通常在最左，學分次之，GPA 最右
            
            # 先確定科目名稱
            if not found_subject_column and potential_subject_columns:
                # 選擇最左邊的潛在科目欄位
                found_subject_column = potential_subject_columns[0] 
            
            # 再確定學分欄位，優先靠近科目名稱
            if not found_credit_column and potential_credit_columns:
                if found_subject_column:
                    subject_col_idx = df.columns.get_loc(found_subject_column)
                    # 尋找在科目欄位右側的學分欄位
                    right_side_candidates = [col for col in potential_credit_columns if df.columns.get_loc(col) > subject_col_idx]
                    if right_side_candidates:
                        # 選擇最靠近科目欄位的學分欄位
                        found_credit_column = sorted(right_side_candidates, key=lambda x: df.columns.get_loc(x))[0]
                    elif potential_credit_columns: # 如果右側沒有，就選第一個
                         found_credit_column = potential_credit_columns[0]
                else: # 如果沒有找到科目名稱，就選第一個潛在學分欄位
                    found_credit_column = potential_credit_columns[0]

            # 最後確定 GPA 欄位，優先靠近學分欄位
            if not found_gpa_column and potential_gpa_columns:
                if found_credit_column:
                    credit_col_idx = df.columns.get_loc(found_credit_column)
                    # 尋找在學分欄位右側的 GPA 欄位
                    right_side_candidates = [col for col in potential_gpa_columns if df.columns.get_loc(col) > credit_col_idx]
                    if right_side_candidates:
                        found_gpa_column = sorted(right_side_candidates, key=lambda x: df.columns.get_loc(x))[0]
                    elif potential_gpa_columns: # 如果右側沒有，就選第一個
                        found_gpa_column = potential_gpa_columns[0]
                else: # 如果沒有找到學分欄位，就選第一個潛在 GPA 欄位
                    found_gpa_column = potential_gpa_columns[0]


        if found_credit_column:
            # st.info(f"從表格 {df_idx + 1} 偵測到學分欄位: '{found_credit_column}'。")
            # if found_subject_column:
            #     st.info(f"從表格 {df_idx + 1} 偵測到科目名稱欄位: '{found_subject_column}'。")
            # if found_gpa_column:
            #     st.info(f"從表格 {df_idx + 1} 偵測到 GPA 欄位: '{found_gpa_column}'。")

            try:
                current_table_credits = 0.0
                for row_idx, row in df.iterrows():
                    item_str = normalize_text(row[found_credit_column])
                    gpa_str = normalize_text(row[found_gpa_column]) if found_gpa_column else ""
                    
                    credit_val = 0.0
                    is_failing_grade = False

                    # 檢查 GPA 是否為不及格
                    if gpa_str:
                        # 簡化 GPA 字符串，例如 "A-" 變成 "A"
                        gpa_clean = re.sub(r'[+\-]', '', gpa_str).upper() 
                        if gpa_clean in failing_grades or gpa_str in ["E", "D", "F"]: # 確保包含 D, E, F
                            is_failing_grade = True

                    # 處理學分值
                    if item_str in ["通過", "抵免", "pass", "exempt", "Pass", "Exempt"]:
                        credit_val = 0.0 # 這些通常不計學分
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
                    
                    course_name = "未知科目" # 預設為未知科目
                    if found_subject_column and found_subject_column in row:
                        course_name = normalize_text(row[found_subject_column])
                        if not course_name: # 如果提取出來的科目名稱是空的，再給一個預設值
                            course_name = "未知科目"


                    if credit_val > 0: # 只記錄有學分的科目
                        if is_failing_grade:
                            # st.write(f"科目 '{course_name}' (學分: {credit_val}, GPA: {gpa_str}) 因不及格不計入總學分。")
                            failed_courses.append({
                                "科目名稱": course_name, 
                                "學分": credit_val, 
                                "GPA": gpa_str, 
                                "來源表格": df_idx + 1,
                                "學年度": normalize_text(row[df.columns[0]]) if len(df.columns)>0 else "", # 嘗試獲取學年度
                                "學期": normalize_text(row[df.columns[1]]) if len(df.columns)>1 else "" # 嘗試獲取學期
                            })
                        else:
                            total_credits += credit_val
                            calculated_courses.append({
                                "科目名稱": course_name, 
                                "學分": credit_val, 
                                "GPA": gpa_str, 
                                "來源表格": df_idx + 1,
                                "學年度": normalize_text(row[df.columns[0]]) if len(df.columns)>0 else "", # 嘗試獲取學年度
                                "學期": normalize_text(row[df.columns[1]]) if len(df.columns)>1 else "" # 嘗試獲取學期
                            })
                # st.write(f"表格 {df_idx + 1} 的學分總計: **{current_table_credits:.2f}**")
                
            except Exception as e:
                st.warning(f"表格 {df_idx + 1} 的學分計算時發生錯誤: `{e}`")
                st.warning("該表格的學分可能無法計入總數。請檢查學分欄位數據是否為純數字或可提取數字。")
        else:
            # st.info(f"表格 {df_idx + 1} 未偵測到明確的學分欄位。檢查欄位：`{list(df.columns)}`。不計入總學分。")
            pass 
            
    return total_credits, calculated_courses, failed_courses

def process_pdf_file(uploaded_file):
    """
    使用 pdfplumber 處理上傳的 PDF 檔案，提取表格。
    """
    all_grades_data = []

    try:
        with pdfplumber.open(uploaded_file) as pdf:
            # st.write(f"正在處理檔案: **{uploaded_file.name}**")
            # num_pages = len(pdf.pages)
            # st.info(f"PDF 總頁數: **{num_pages}**")

            for page_num, page in enumerate(pdf.pages):
                # st.subheader(f"頁面 {page_num + 1}") 

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
                        # st.markdown(f"**頁面 {page_num + 1} 的表格 {table_idx + 1}**")
                        
                        processed_table = []
                        for row in table:
                            normalized_row = [normalize_text(cell) for cell in row]
                            processed_table.append(normalized_row)
                        
                        if not processed_table:
                            st.info(f"頁面 {page_num + 1} 的表格 **{table_idx + 1}** 提取後為空。")
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
                                # st.dataframe(df_table) 
                            except Exception as e_df:
                                st.error(f"頁面 {page_num + 1} 表格 {table_idx + 1} 轉換為 DataFrame 時發生錯誤: `{e_df}`")
                                st.error(f"原始處理後數據範例: {processed_table[:2]} (前兩行)")
                                st.error(f"生成的唯一欄位名稱: {unique_columns}")
                        else:
                            st.info(f"頁面 {page_num + 1} 的表格 **{table_idx + 1}** 沒有數據行。")

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
            total_credits, calculated_courses, failed_courses = calculate_total_credits(extracted_dfs)

            st.markdown("---")
            st.markdown("## ✅ 查詢結果") 
            st.markdown(f"目前總學分: <span style='color:green; font-size: 24px;'>**{total_credits:.2f}**</span>", unsafe_allow_html=True)
            
            # 輸入目標學分
            target_credits = st.number_input("輸入您的目標學分 (例如：128)", min_value=0.0, value=128.0, step=1.0, 
                                            help="您可以設定一個畢業學分目標，工具會幫您計算還差多少學分。")
            
            credit_difference = target_credits - total_credits
            if credit_difference > 0:
                st.write(f"距離畢業所需學分 (共{target_credits:.0f}學分) **{credit_difference:.2f}**")
            elif credit_difference < 0:
                st.write(f"已超越畢業所需學分 (共{target_credits:.0f}學分) **{abs(credit_difference):.2f}**")
            else:
                st.write(f"已達到畢業所需學分 (共{target_credits:.0f}學分) **0.00**")


            st.markdown("---")
            st.markdown("### 📚 通過的課程列表") 
            if calculated_courses:
                courses_df = pd.DataFrame(calculated_courses)
                # 確保欄位順序與截圖一致，且只包含 GPA 和學分
                # GPA欄位如果數據為空或無法識別，會是空字符串，這裡可以根據實際提取的數據決定是否顯示GPA
                display_cols = ['學年度', '學期', '科目名稱', '學分', 'GPA']
                # 過濾掉不在DataFrame中的欄位
                final_display_cols = [col for col in display_cols if col in courses_df.columns]
                
                st.dataframe(courses_df[final_display_cols], height=300, use_container_width=True) 
            else:
                st.info("沒有找到可以計算學分的科目。")

            if failed_courses:
                st.markdown("---")
                st.markdown("### ⚠️ 不及格或不計學分的課程列表")
                failed_df = pd.DataFrame(failed_courses)
                # 顯示所有相關資訊，以便用戶檢查
                display_failed_cols = ['學年度', '學期', '科目名稱', '學分', 'GPA', '來源表格']
                final_display_failed_cols = [col for col in display_failed_cols if col in failed_df.columns]
                st.dataframe(failed_df[final_display_failed_cols], height=200, use_container_width=True)
                st.info("這些科目因成績不及格 ('D', 'E', 'F' 等) 或被標記為 '通過'/'抵免' 而未計入總學分。")


            # 提供下載選項 
            if calculated_courses or failed_courses:
                # 可以考慮提供兩個下載按鈕，一個是通過的，一個是不及格的
                if calculated_courses:
                    csv_data_passed = pd.DataFrame(calculated_courses).to_csv(index=False, encoding='utf-8-sig')
                    st.download_button(
                        label="下載通過的科目列表為 CSV",
                        data=csv_data_passed,
                        file_name=f"{uploaded_file.name.replace('.pdf', '')}_calculated_courses.csv",
                        mime="text/csv",
                        key="download_passed_btn"
                    )
                if failed_courses:
                    csv_data_failed = pd.DataFrame(failed_courses).to_csv(index=False, encoding='utf-8-sig')
                    st.download_button(
                        label="下載不及格的科目列表為 CSV",
                        data=csv_data_failed,
                        file_name=f"{uploaded_file.name.replace('.pdf', '')}_failed_courses.csv",
                        mime="text/csv",
                        key="download_failed_btn"
                    )
            
        else:
            st.warning("未從 PDF 中提取到任何表格數據。請檢查 PDF 內容或嘗試調整 `pdfplumber` 的表格提取設定。")
    else:
        st.info("請上傳 PDF 檔案以開始處理。")

if __name__ == "__main__":
    main()
