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
    # 檢查是否是 pdfplumber 的 Text 物件 (它會有 .text 屬性)
    if hasattr(cell_content, 'text'):
        text = str(cell_content.text)
    # 如果不是 Text 物件，但本身是字串
    elif isinstance(cell_content, str):
        text = cell_content
    # 其他情況，嘗試轉換為字串
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
        
        # 對於空字串或過短的字串，使用 'Column_X' 格式
        if not original_col_cleaned or len(original_col_cleaned) < 2: 
            name_base = "Column"
            # 確保生成的 Column_X 是在 unique_columns 中唯一的
            current_idx = 1
            while f"{name_base}_{current_idx}" in unique_columns:
                current_idx += 1
            name = f"{name_base}_{current_idx}"
        else:
            name = original_col_cleaned
        
        # 處理名稱本身的重複
        final_name = name
        counter = seen[name]
        # 如果當前生成的名稱已經存在於 unique_columns 中，則添加後綴
        while final_name in unique_columns:
            counter += 1
            final_name = f"{name}_{counter}" 
        
        unique_columns.append(final_name)
        seen[name] = counter # 更新該基礎名稱的最大計數

    return unique_columns

def parse_credit_and_gpa(text):
    """
    從單元格文本中解析學分和 GPA。
    考慮 "A 2" (GPA在左，學分在右) 和 "2 A" (學分在左，GPA在右) 的情況。
    返回 (學分, GPA)。如果解析失敗，返回 (0.0, "")。
    """
    text_clean = normalize_text(text)
    
    # 首先檢查是否是「通過」或「抵免」等關鍵詞
    if text_clean.lower() in ["通過", "抵免", "pass", "exempt"]:
        # 如果是這些關鍵詞，學分通常不會直接在字串中，但可能在其他欄位
        # 在此函數中，我們只解析當前單元格的內容。如果單元格只有這些詞，則學分為0
        # 實際學分會在 calculate_total_credits 中從學分欄位獲取
        return 0.0, text_clean # 返回解析到的「通過」等字串作為 GPA

    # 嘗試匹配 "GPA 學分" 模式 (例如 "A 2", "C- 3")
    match_gpa_credit = re.match(r'([A-Fa-f][+\-]?)\s*(\d+(\.\d+)?)', text_clean)
    if match_gpa_credit:
        gpa = match_gpa_credit.group(1).upper()
        try:
            credit = float(match_gpa_credit.group(2))
            return credit, gpa
        except ValueError:
            pass # 繼續嘗試其他模式

    # 嘗試匹配 "學分 GPA" 模式 (例如 "2 A", "3 B-")
    match_credit_gpa = re.match(r'(\d+(\.\d+)?)\s*([A-Fa-f][+\-]?)', text_clean)
    if match_credit_gpa:
        try:
            credit = float(match_credit_gpa.group(1))
            gpa = match_credit_gpa.group(3).upper()
            return credit, gpa
        except ValueError:
            pass # 繼續嘗試其他模式
            
    # 嘗試只匹配學分 (純數字)
    credit_only_match = re.search(r'(\d+(\.\d+)?)', text_clean)
    if credit_only_match:
        try:
            credit = float(credit_only_match.group(1))
            # 如果只有學分，GPA 設為空
            return credit, "" 
        except ValueError:
            pass

    # 嘗試只匹配 GPA (純字母)
    gpa_only_match = re.search(r'([A-Fa-f][+\-]?)', text_clean)
    if gpa_only_match:
        # 如果只有 GPA，學分設為 0
        return 0.0, gpa_only_match.group(1).upper()

    return 0.0, ""

def is_grades_table(df):
    """
    判斷一個 DataFrame 是否為有效的成績單表格。
    透過檢查是否存在預期的欄位關鍵字來判斷。
    """
    # 將欄位名稱轉換為小寫並去除空白，以便進行不區分大小寫的匹配
    normalized_columns = [re.sub(r'\s+', '', col).lower() for col in df.columns.tolist()]
    
    # 定義判斷成績表格的核心關鍵字
    # 這裡的關鍵字應該是成績單表格特有的，而不是其他信息表格也可能有的
    # 例如：科目名稱、學分、GPA、學期、學年
    credit_keywords = ["學分", "credits", "credit", "學分數"]
    gpa_keywords = ["gpa", "成績", "grade"]
    subject_keywords = ["科目名稱", "課程名稱", "coursename", "subjectname", "科目", "課程"]
    year_sem_keywords = ["學年", "學期", "year", "semester"]

    # 檢查是否存在至少一個學分或GPA關鍵字
    has_credit_or_gpa_col = any(any(k in col for k in credit_keywords) for col in normalized_columns) or \
                            any(any(k in col for k in gpa_keywords) for col in normalized_columns)

    # 檢查是否存在至少一個科目名稱關鍵字
    has_subject_col = any(any(k in col for k in subject_keywords) for col in normalized_columns)

    # 檢查是否存在學年或學期關鍵字
    has_year_sem_col = any(any(k in col for k in year_sem_keywords) for col in normalized_columns)

    # 如果同時有科目、學分/GPA、學年/學期，則很可能是成績表格
    if has_subject_col and has_credit_or_gpa_col and has_year_sem_col:
        return True
    
    # 更靈活的判斷：如果表格有足夠多的行，並且其中的一些單元格內容看起來像課程名、學分或GPA
    if len(df) > 5: # 至少有5行數據才進行更深層的判斷
        # 檢查是否存在一列，其大部分內容看起來像科目名稱
        potential_subject_col_data_count = 0
        for col_name in df.columns:
            sample_data = df[col_name].head(len(df)).apply(normalize_text).tolist() # 檢查所有行
            
            # 計數看起來像科目名稱的單元格 (包含中文字符，長度>4，不是純數字或單個字母成績)
            subject_like_cells = sum(1 for item_str in sample_data 
                                     if re.search(r'[\u4e00-\u9fa5]', item_str) and len(item_str) > 4 
                                     and not item_str.isdigit() and not re.match(r'^[A-Fa-f][+\-]?$', item_str)
                                     and not item_str.lower() in ["通過", "抵免", "pass", "exempt"])
            
            if subject_like_cells / len(sample_data) >= 0.5: # 如果超過一半的單元格像科目名稱
                potential_subject_col_data_count += 1
        
        # 如果至少有一列看起來像科目名稱列，且之前沒有明確的欄位匹配
        if potential_subject_col_data_count > 0:
            return True


    return False


def calculate_total_credits(df_list):
    """
    從提取的 DataFrames 列表中計算總學分。
    尋找包含 '學分' 或 '學分(GPA)' 類似字樣的欄位進行加總。
    返回總學分和計算學分的科目列表，以及不及格科目列表。
    """
    total_credits = 0.0
    calculated_courses = [] 
    failed_courses = [] 

    credit_column_keywords = ["學分", "學分數", "學分(GPA)", "學 分", "Credits", "Credit"] 
    subject_column_keywords = ["科目名稱", "課程名稱", "Course Name", "Subject Name", "科目", "課程"] 
    gpa_column_keywords = ["GPA", "成績", "Grade"] 
    
    # 更新不及格判斷，不再包含「通過」或「抵免」
    failing_grades = ["D", "D-", "E", "F", "X", "不通過", "未通過", "不及格"] 

    for df_idx, df in enumerate(df_list):
        found_credit_column = None
        found_subject_column = None 
        found_gpa_column = None 
        
        # 步驟 1: 優先匹配明確的學分、科目和 GPA 關鍵字
        for col_name_orig in df.columns:
            cleaned_col_for_match = "".join(char for char in normalize_text(col_name_orig) if '\u4e00' <= char <= '\u9fa5' or 'a' <= char <= 'z' or 'A' <= char <= 'Z' or '0' <= char <= '9').strip()
            
            if any(keyword in cleaned_col_for_match for keyword in credit_column_keywords):
                found_credit_column = col_name_orig 
            if any(keyword in cleaned_col_for_match for keyword in subject_column_keywords):
                found_subject_column = col_name_orig
            if any(keyword in cleaned_col_for_match for keyword in gpa_column_keywords):
                found_gpa_column = col_name_orig
            
            if found_credit_column and found_subject_column and found_gpa_column:
                break 
        
        # 步驟 2: 如果沒有明確匹配，嘗試從通用名稱 (Column_X) 中猜測欄位
        potential_credit_columns = []
        potential_subject_columns = []
        potential_gpa_columns = []

        for col_name in df.columns: 
            sample_data = df[col_name].head(10).apply(normalize_text).tolist()
            total_sample_count = len(sample_data)

            # 判斷潛在學分欄位
            numeric_like_count = 0
            for item_str in sample_data:
                credit_val, _ = parse_credit_and_gpa(item_str)
                if 0.0 < credit_val <= 10.0: # 學分大於0且在合理範圍內
                    numeric_like_count += 1
            if total_sample_count > 0 and numeric_like_count / total_sample_count >= 0.6: 
                potential_credit_columns.append(col_name)

            # 判斷潛在科目名稱欄位 (更智能的判斷)
            subject_like_count = 0
            for item_str in sample_data:
                if re.search(r'[\u4e00-\u9fa5]', item_str) and len(item_str) > 4 and not item_str.isdigit() and not re.match(r'^[A-Fa-f][+\-]?$', item_str) and not item_str.lower() in ["通過", "抵免", "pass", "exempt"]: 
                    subject_like_count += 1
            if total_sample_count > 0 and subject_like_count / total_sample_count >= 0.7: 
                potential_subject_columns.append(col_name)

            # 判斷潛在 GPA 欄位
            gpa_like_count = 0
            for item_str in sample_data:
                if re.match(r'^[A-Fa-f][+\-]?' , item_str) or (item_str.isdigit() and len(item_str) <=3) or item_str.lower() in ["通過", "抵免", "pass", "exempt"]: 
                    gpa_like_count += 1
            if total_sample_count > 0 and gpa_like_count / total_sample_count >= 0.6: 
                potential_gpa_columns.append(col_name)

        # 步驟 3: 根據推斷結果確定學分、科目和 GPA 欄位
        # 確保優先級：科目名稱通常在最左，學分次之，GPA 最右
        
        # 先確定科目名稱
        if not found_subject_column and potential_subject_columns:
            # 選擇最左邊的潛在科目欄位
            found_subject_column = sorted(potential_subject_columns, key=lambda x: df.columns.get_loc(x))[0]
        
        # 再確定學分欄位，優先靠近科目名稱
        if not found_credit_column and potential_credit_columns:
            if found_subject_column:
                subject_col_idx = df.columns.get_loc(found_subject_column)
                # 尋找在科目欄位右側的學分欄位
                right_side_candidates = [col for col in potential_credit_columns if df.columns.get_loc(col) > subject_col_idx]
                if right_side_candidates:
                    found_credit_column = sorted(right_side_candidates, key=lambda x: df.columns.get_loc(x))[0]
                elif potential_credit_columns: 
                     found_credit_column = potential_credit_columns[0]
            else: 
                found_credit_column = potential_credit_columns[0]

        # 最後確定 GPA 欄位，優先靠近學分欄位
        if not found_gpa_column and potential_gpa_columns:
            if found_credit_column:
                credit_col_idx = df.columns.get_loc(found_credit_column)
                # 尋找在學分欄位右側的 GPA 欄位
                right_side_candidates = [col for col in potential_gpa_columns if df.columns.get_loc(col) > credit_col_idx]
                if right_side_candidates:
                    found_gpa_column = sorted(right_side_candidates, key=lambda x: df.columns.get_loc(x))[0]
                elif potential_gpa_columns: 
                    found_gpa_column = potential_gpa_columns[0]
            else: 
                found_gpa_column = potential_gpa_columns[0]


        if found_credit_column: # 只有找到學分欄位才進行處理
            try:
                for row_idx, row in df.iterrows():
                    # 嘗試從學分或 GPA 欄位獲取學分和 GPA
                    extracted_credit = 0.0
                    extracted_gpa = ""

                    # 從學分欄位提取學分和潛在的GPA
                    if found_credit_column in row: # 確保欄位存在於當前行
                        extracted_credit, extracted_gpa_from_credit_col = parse_credit_and_gpa(row[found_credit_column])
                        if extracted_gpa_from_credit_col: 
                            extracted_gpa = extracted_gpa_from_credit_col
                    
                    # 如果GPA欄位存在且目前沒有獲取到GPA，則從GPA欄位獲取
                    if found_gpa_column in row and not extracted_gpa: # 確保欄位存在於當前行
                        gpa_from_gpa_col = normalize_text(row[found_gpa_column])
                        if gpa_from_gpa_col:
                            extracted_gpa = gpa_from_gpa_col.upper()
                    
                    # 確保學分值不為 None
                    if extracted_credit is None:
                        extracted_credit = 0.0

                    is_failing_grade = False
                    # 檢查是否為不及格成績，不包含「通過」或「抵免」
                    if extracted_gpa:
                        gpa_clean = re.sub(r'[+\-]', '', extracted_gpa).upper() 
                        if gpa_clean in failing_grades:
                            is_failing_grade = True
                        elif gpa_clean.isdigit(): # 如果 GPA 是數字，例如分數，假設60分以下不及格 (可根據學校標準調整)
                            try:
                                numeric_gpa = float(gpa_clean)
                                if numeric_gpa < 60: # 假設 60 分以下為不及格
                                    is_failing_grade = True
                            except ValueError:
                                pass
                    
                    # 處理「通過」和「抵免」情況：現在它們會被計入學分，除非學分為0
                    is_passed_or_exempt_grade = False
                    if (found_gpa_column in row and normalize_text(row[found_gpa_column]).lower() in ["通過", "抵免", "pass", "exempt"]) or \
                       (found_credit_column in row and normalize_text(row[found_credit_column]).lower() in ["通過", "抵免", "pass", "exempt"]):
                        is_passed_or_exempt_grade = True
                        
                    course_name = "未知科目" 
                    if found_subject_column in row: # 確保欄位存在於當前行
                        temp_name = normalize_text(row[found_subject_column])
                        if len(temp_name) > 2 and re.search(r'[\u4e00-\u9fa5]', temp_name): # 確保是有效的中文科目名
                            course_name = temp_name
                        elif not temp_name: # 如果科目名稱欄位是空的，嘗試從前一列獲取（常見於合併單元格）
                            try:
                                current_col_idx = df.columns.get_loc(found_subject_column)
                                if current_col_idx > 0: 
                                    prev_col_name = df.columns[current_col_idx - 1]
                                    if prev_col_name in row: # 確保前一列存在於當前行
                                        temp_name_prev_col = normalize_text(row[prev_col_name])
                                        if len(temp_name_prev_col) > 2 and re.search(r'[\u4e00-\u9fa5]', temp_name_prev_col):
                                            course_name = temp_name_prev_col
                            except Exception:
                                pass

                    # 嘗試獲取學年度和學期
                    acad_year = ""
                    semester = ""
                    # 這些通常在表格的前兩列
                    if len(df.columns) > 0 and df.columns[0] in row:
                        acad_year = normalize_text(row[df.columns[0]])
                    if len(df.columns) > 1 and df.columns[1] in row:
                        semester = normalize_text(row[df.columns[1]])


                    # 判斷是否計入總學分或不及格學分
                    # 只有在 extracted_credit > 0 或者明確有「通過/抵免」標記的情況下，才被視為有效課程。
                    # 同時，若被判斷為不及格，則歸類到不及格列表。
                    if is_failing_grade:
                        failed_courses.append({
                            "學年度": acad_year,
                            "學期": semester,
                            "科目名稱": course_name, 
                            "學分": extracted_credit, 
                            "GPA": extracted_gpa, 
                            "來源表格": df_idx + 1
                        })
                    elif extracted_credit > 0 or is_passed_or_exempt_grade: # 如果學分大於0，或成績是通過/抵免，就視為通過課程
                        # 只有學分大於0才加總，即使是「通過/抵免」但學分是0，也不計入總學分，只列出
                        if extracted_credit > 0: 
                            total_credits += extracted_credit
                        calculated_courses.append({
                            "學年度": acad_year,
                            "學期": semester,
                            "科目名稱": course_name, 
                            "學分": extracted_credit, 
                            "GPA": extracted_gpa, 
                            "來源表格": df_idx + 1
                        })
                
            except Exception as e:
                st.warning(f"表格 {df_idx + 1} 的學分計算時發生錯誤: `{e}`。該表格的學分可能無法計入總數。請檢查學分和GPA欄位數據是否正確。")
        else:
            # 如果沒有找到學分欄位，則該表格不應被視為成績單，此處不再顯示額外警告，因為is_grades_table已處理
            pass 
            
    return total_credits, calculated_courses, failed_courses

def process_pdf_file(uploaded_file):
    """
    使用 pdfplumber 處理上傳的 PDF 檔案，提取表格。
    此函數內部將減少 Streamlit 的直接輸出，只返回提取的數據。
    """
    all_grades_data = []

    try:
        with pdfplumber.open(uploaded_file) as pdf:
            for page_num, page in enumerate(pdf.pages):
                current_page = page 

                table_settings = {
                    "vertical_strategy": "lines", 
                    "horizontal_strategy": "lines", 
                    "snap_tolerance": 3,  
                    "join_tolerance": 5,  
                    "edge_min_length": 3, 
                    "text_tolerance": 2,  
                    "min_words_vertical": 1, 
                    "min_words_horizontal": 1, 
                }
                
                try:
                    tables = current_page.extract_tables(table_settings)

                    if not tables:
                        st.info(f"頁面 **{page_num + 1}** 未偵測到表格。這可能是由於 PDF 格式複雜或表格提取設定不適用。")
                        continue

                    for table_idx, table in enumerate(tables):
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
                                # 使用 is_grades_table 函數來過濾非成績單表格
                                if is_grades_table(df_table):
                                    all_grades_data.append(df_table)
                                    st.success(f"頁面 {page_num + 1} 的表格 {table_idx + 1} 已識別為成績單表格並已處理。")
                                else:
                                    # 顯示更詳細的跳過原因，可以幫助用戶理解
                                    st.info(f"頁面 {page_num + 1} 的表格 {table_idx + 1} (標題範例: {header_row}) 未識別為成績單表格，已跳過。")
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
            
            target_credits = st.number_input("輸入您的目標學分 (例如：128)", min_value=0.0, value=128.0, step=1.0, 
                                            help="您可以設定一個畢業學分目標，工具會幫您計算還差多少學分。")
            
            credit_difference = target_credits - total_credits
            if credit_difference > 0:
                st.write(f"距離畢業所需學分 (共{target_credits:.0f}學分) **{credit_difference:.2f}**")
            elif credit_difference < 0:
                st.write(f"已超越畢業學分 (共{target_credits:.0f}學分) **{abs(credit_difference):.2f}**")
            else:
                st.write(f"已達到畢業所需學分 (共{target_credits:.0f}學分) **0.00**")


            st.markdown("---")
            st.markdown("### 📚 通過的課程列表") 
            if calculated_courses:
                courses_df = pd.DataFrame(calculated_courses)
                # 確保欄位順序與截圖一致，且只包含 GPA 和學分
                display_cols = ['學年度', '學期', '科目名稱', '學分', 'GPA']
                final_display_cols = [col for col in display_cols if col in courses_df.columns]
                
                st.dataframe(courses_df[final_display_cols], height=300, use_container_width=True) 
            else:
                st.info("沒有找到可以計算學分的科目。")

            if failed_courses:
                st.markdown("---")
                st.markdown("### ⚠️ 不及格的課程列表")
                failed_df = pd.DataFrame(failed_courses)
                display_failed_cols = ['學年度', '學期', '科目名稱', '學分', 'GPA', '來源表格']
                final_display_failed_cols = [col for col in display_failed_cols if col in failed_df.columns]
                st.dataframe(failed_df[final_display_failed_cols], height=200, use_container_width=True)
                st.info("這些科目因成績不及格 ('D', 'E', 'F' 等) 而未計入總學分。") # 更新訊息

            # 提供下載選項 
            if calculated_courses or failed_courses:
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
