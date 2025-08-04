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
    透過檢查是否存在預期的欄位關鍵字和數據內容模式來判斷。
    """
    if df.empty or len(df.columns) < 3: #至少3列才可能是成績單表格 (學年、科目、學分/GPA)
        return False

    # 將欄位名稱轉換為小寫並去除空白，以便進行不區分大小寫的匹配
    normalized_columns = [re.sub(r'\s+', '', col).lower() for col in df.columns.tolist()]
    
    # 定義判斷成績表格的核心關鍵字
    credit_keywords = ["學分", "credits", "credit", "學分數"]
    gpa_keywords = ["gpa", "成績", "grade", "gpa(數值)"] 
    subject_keywords = ["科目名稱", "課程名稱", "coursename", "subjectname", "科目", "課程"]
    year_keywords = ["學年", "year"] # 將學年和學期分開判斷
    semester_keywords = ["學期", "semester"]

    # 步驟1: 檢查明確的表頭關鍵字匹配
    has_credit_col_header = any(any(k in col for k in credit_keywords) for col in normalized_columns)
    has_gpa_col_header = any(any(k in col for k in gpa_keywords) for col in normalized_columns)
    has_subject_col_header = any(any(k in col for k in subject_keywords) for col in normalized_columns)
    has_year_col_header = any(any(k in col for k in year_keywords) for col in normalized_columns)
    has_semester_col_header = any(any(k in col for k in semester_keywords) for col in normalized_columns)


    # 如果明確匹配到核心欄位，則很可能是成績表格
    if has_subject_col_header and (has_credit_col_header or has_gpa_col_header) and has_year_col_header and has_semester_col_header:
        return True
    
    # 步驟2: 如果沒有明確表頭匹配，則檢查數據行的內容模式 (更具彈性)
    # 我們需要找到至少一列像科目名稱，一列像學分/GPA，一列像學年，一列像學期
    
    potential_subject_cols = []
    potential_credit_gpa_cols = []
    potential_year_cols = []
    potential_semester_cols = []

    # 只取前20行或所有行（如果少於20行）作為樣本，以確保覆蓋足夠多的數據
    sample_rows_df = df.head(min(len(df), 20)) 

    for col_name in df.columns:
        sample_data = sample_rows_df[col_name].apply(normalize_text).tolist()
        total_sample_count = len(sample_data)
        if total_sample_count == 0:
            continue

        # 判斷潛在科目名稱欄位: 包含中文字符，長度通常較長 (>4個字), 且不全是數字或單個字母成績/通過/抵免
        subject_like_cells = sum(1 for item_str in sample_data 
                                 if re.search(r'[\u4e00-\u9fa5]', item_str) and len(item_str) >= 2 # 修改此處，放寬到>=2個字
                                 and not item_str.isdigit() and not re.match(r'^[A-Fa-f][+\-]?$', item_str)
                                 and not item_str.lower() in ["通過", "抵免", "pass", "exempt"])
        if subject_like_cells / total_sample_count >= 0.4: # 放寬條件，只要40%像科目名稱
            potential_subject_cols.append(col_name)

        # 判斷潛在學分/GPA欄位: 包含數字或標準GPA等級或通過/抵免
        credit_gpa_like_cells = 0
        for item_str in sample_data:
            credit_val, gpa_val = parse_credit_and_gpa(item_str)
            if (0.0 < credit_val <= 10.0) or (gpa_val and re.match(r'^[A-Fa-f][+\-]?$', gpa_val)) or (item_str.lower() in ["通過", "抵免", "pass", "exempt"]):
                credit_gpa_like_cells += 1
        if credit_gpa_like_cells / total_sample_count >= 0.4: # 放寬條件
            potential_credit_gpa_cols.append(col_name)

        # 判斷潛在學年欄位: 類似 "111", "2023" 這樣的數字格式
        year_like_cells = sum(1 for item_str in sample_data 
                                  if (item_str.isdigit() and (len(item_str) == 3 or len(item_str) == 4))) # 允許3位數(民國年)或4位數(西元年)
        if year_like_cells / total_sample_count >= 0.6: # 大部分單元格像學年
            potential_year_cols.append(col_name)

        # 判斷潛在學期欄位: 類似 "上", "下", "1", "2" 這樣的格式
        semester_like_cells = sum(1 for item_str in sample_data 
                                  if item_str.lower() in ["上", "下", "春", "夏", "秋", "冬", "1", "2", "3", "春季", "夏季", "秋季", "冬季", "spring", "summer", "fall", "winter"])
        if semester_like_cells / total_sample_count >= 0.6: # 大部分單元格像學期
            potential_semester_cols.append(col_name)


    # 如果能找到至少一個科目列，一個學分/GPA列，一個學年列，和一個學期列，則判斷為成績表格
    if potential_subject_cols and potential_credit_gpa_cols and potential_year_cols and potential_semester_cols:
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

    # 關鍵字列表
    credit_column_keywords = ["學分", "學分數", "學分(GPA)", "學 分", "Credits", "Credit", "學分數(學分)"] 
    subject_column_keywords = ["科目名稱", "課程名稱", "Course Name", "Subject Name", "科目", "課程"] 
    gpa_column_keywords = ["GPA", "成績", "Grade", "gpa(數值)"] 
    year_column_keywords = ["學年", "year", "學 年"]
    semester_column_keywords = ["學期", "semester", "學 期"]
    
    # 更新不及格判斷，不再包含「通過」或「抵免」
    failing_grades = ["D", "D-", "E", "F", "X", "不通過", "未通過", "不及格"] 

    for df_idx, df in enumerate(df_list):
        if df.empty or len(df.columns) < 3: # 無效DF跳過
            continue

        found_credit_column = None
        found_subject_column = None 
        found_gpa_column = None 
        found_year_column = None
        found_semester_column = None
        
        # 步驟 1: 優先匹配明確的表頭關鍵字
        normalized_df_columns = {re.sub(r'\s+', '', col_name).lower(): col_name for col_name in df.columns}
        
        for k in credit_column_keywords:
            if k in normalized_df_columns:
                found_credit_column = normalized_df_columns[k]
                break
        for k in subject_column_keywords:
            if k in normalized_df_columns:
                found_subject_column = normalized_df_columns[k]
                break
        for k in gpa_column_keywords:
            if k in normalized_df_columns:
                found_gpa_column = normalized_df_columns[k]
                break
        for k in year_column_keywords:
            if k in normalized_df_columns:
                found_year_column = normalized_df_columns[k]
                break
        for k in semester_column_keywords:
            if k in normalized_df_columns:
                found_semester_column = normalized_df_columns[k]
                break

        # 步驟 2: 如果沒有明確匹配，則回退到根據數據內容猜測欄位
        potential_credit_cols = []
        potential_subject_cols = []
        potential_gpa_cols = []
        potential_year_cols = []
        potential_semester_cols = []

        sample_rows_df = df.head(min(len(df), 20)) # 只取前20行或所有行作為樣本

        for col_name in df.columns: 
            sample_data = sample_rows_df[col_name].apply(normalize_text).tolist()
            total_sample_count = len(sample_data)
            if total_sample_count == 0:
                continue

            # 判斷潛在學分欄位
            credit_vals_found = 0
            for item_str in sample_data:
                credit_val, _ = parse_credit_and_gpa(item_str)
                if 0.0 < credit_val <= 10.0: 
                    credit_vals_found += 1
            if credit_vals_found / total_sample_count >= 0.4: # 放寬至0.4
                potential_credit_cols.append(col_name)

            # 判斷潛在科目名稱欄位
            subject_vals_found = 0
            for item_str in sample_data:
                # 修改此處，放寬到 >= 2 個字，並確保包含中文字符且不是純數字或成績
                if re.search(r'[\u4e00-\u9fa5]', item_str) and len(item_str) >= 2 and not item_str.isdigit() and not re.match(r'^[A-Fa-f][+\-]?$', item_str) and not item_str.lower() in ["通過", "抵免", "pass", "exempt"]: 
                    subject_vals_found += 1
            if subject_vals_found / total_sample_count >= 0.4: # 放寬至0.4
                potential_subject_cols.append(col_name)

            # 判斷潛在 GPA 欄位
            gpa_vals_found = 0
            for item_str in sample_data:
                if re.match(r'^[A-Fa-f][+\-]?' , item_str) or (item_str.isdigit() and len(item_str) <=3) or item_str.lower() in ["通過", "抵免", "pass", "exempt"]: 
                    gpa_vals_found += 1
            if gpa_vals_found / total_sample_count >= 0.4: # 放寬至0.4
                potential_gpa_cols.append(col_name)

            # 判斷潛在學年欄位
            year_vals_found = 0
            for item_str in sample_data:
                if (item_str.isdigit() and (len(item_str) == 3 or len(item_str) == 4)):
                    year_vals_found += 1
            if year_vals_found / total_sample_count >= 0.6: 
                potential_year_cols.append(col_name)

            # 判斷潛在學期欄位
            semester_vals_found = 0
            for item_str in sample_data:
                if item_str.lower() in ["上", "下", "春", "夏", "秋", "冬", "1", "2", "3", "春季", "夏季", "秋季", "冬季", "spring", "summer", "fall", "winter"]:
                    semester_vals_found += 1
            if semester_vals_found / total_sample_count >= 0.6: 
                potential_semester_cols.append(col_name)

        # 根據推斷結果確定學分、科目、GPA、學年、學期欄位
        # 優先級：學年、學期在最左，科目次之，學分、GPA在右側
        
        # 優先確定學年和學期 (通常在表格最左側)
        if not found_year_column and potential_year_cols:
            found_year_column = sorted(potential_year_cols, key=lambda x: df.columns.get_loc(x))[0]
        if not found_semester_column and potential_semester_cols:
            # 選擇最靠近學年且符合條件的學期欄位
            if found_year_column:
                year_col_idx = df.columns.get_loc(found_year_column)
                candidates = [col for col in potential_semester_cols if df.columns.get_loc(col) > year_col_idx]
                if candidates:
                    found_semester_column = sorted(candidates, key=lambda x: df.columns.get_loc(x))[0]
                elif potential_semester_cols:
                    found_semester_column = potential_semester_cols[0]
            else:
                found_semester_column = sorted(potential_semester_cols, key=lambda x: df.columns.get_loc(x))[0]

        # 確定科目名稱
        if not found_subject_column and potential_subject_cols:
            if found_semester_column: # 優先在學期欄位右側找科目
                sem_col_idx = df.columns.get_loc(found_semester_column)
                candidates = [col for col in potential_subject_cols if df.columns.get_loc(col) > sem_col_idx]
                if candidates:
                    found_subject_column = sorted(candidates, key=lambda x: df.columns.get_loc(x))[0]
                elif potential_subject_cols:
                    found_subject_column = potential_subject_cols[0]
            else: # 如果沒找到學期，就找最左的科目欄位
                found_subject_column = sorted(potential_subject_cols, key=lambda x: df.columns.get_loc(x))[0]

        # 確定學分欄位
        if not found_credit_column and potential_credit_cols:
            if found_subject_column: # 優先在科目名稱右側找學分
                subject_col_idx = df.columns.get_loc(found_subject_column)
                candidates = [col for col in potential_credit_cols if df.columns.get_loc(col) > subject_col_idx]
                if candidates:
                    found_credit_column = sorted(candidates, key=lambda x: df.columns.get_loc(x))[0]
                elif potential_credit_cols:
                    found_credit_column = potential_credit_cols[0]
            else:
                found_credit_column = sorted(potential_credit_cols, key=lambda x: df.columns.get_loc(x))[0]

        # 確定 GPA 欄位
        if not found_gpa_column and potential_gpa_cols:
            if found_credit_column: # 優先在學分欄位右側找 GPA
                credit_col_idx = df.columns.get_loc(found_credit_column)
                candidates = [col for col in potential_gpa_cols if df.columns.get_loc(col) > credit_col_idx]
                if candidates:
                    found_gpa_column = sorted(candidates, key=lambda x: df.columns.get_loc(x))[0]
                elif potential_gpa_cols:
                    found_gpa_column = potential_gpa_cols[0]
            else:
                found_gpa_column = sorted(potential_gpa_cols, key=lambda x: df.columns.get_loc(x))[0]


        # 必須至少找到科目和學分欄位才能有效處理課程數據
        if found_credit_column and found_subject_column: 
            try:
                for row_idx, row in df.iterrows():
                    # 檢查行是否完全空白，跳過空白行
                    if all(normalize_text(str(cell)) == "" for cell in row):
                        continue

                    extracted_credit = 0.0
                    extracted_gpa = ""

                    # 從學分欄位提取學分和潛在的GPA
                    if found_credit_column in row and pd.notna(row[found_credit_column]): 
                        extracted_credit, extracted_gpa_from_credit_col = parse_credit_and_gpa(row[found_credit_column])
                        if extracted_gpa_from_credit_col and not extracted_gpa: # 如果 GPA 還未被設定，則設定
                            extracted_gpa = extracted_gpa_from_credit_col
                    
                    # 如果GPA欄位存在且目前沒有獲取到GPA，則從GPA欄位獲取
                    # 或者如果GPA欄位提供了更完整的GPA信息，則更新
                    if found_gpa_column and found_gpa_column in row and pd.notna(row[found_gpa_column]): 
                        gpa_from_gpa_col_raw = normalize_text(row[found_gpa_column])
                        # 再次嘗試從 GPA 欄位解析，看是否能提取學分和 GPA
                        parsed_credit_from_gpa_col, parsed_gpa_from_gpa_col = parse_credit_and_gpa(gpa_from_gpa_col_raw)
                        
                        if parsed_gpa_from_gpa_col:
                            extracted_gpa = parsed_gpa_from_gpa_col.upper()
                        
                        if parsed_credit_from_gpa_col > 0 and extracted_credit == 0.0: # 如果學分欄位沒找到學分，但 GPA 欄位找到了，則更新
                            extracted_credit = parsed_credit_from_gpa_col
                    
                    # 確保學分值不為 None
                    if extracted_credit is None:
                        extracted_credit = 0.0

                    is_failing_grade = False
                    if extracted_gpa:
                        gpa_clean = re.sub(r'[+\-]', '', extracted_gpa).upper() 
                        if gpa_clean in failing_grades:
                            is_failing_grade = True
                        elif gpa_clean.isdigit(): 
                            try:
                                numeric_gpa = float(gpa_clean)
                                if numeric_gpa < 60: 
                                    is_failing_grade = True
                            except ValueError:
                                pass
                    
                    is_passed_or_exempt_grade = False
                    if (found_gpa_column in row and pd.notna(row[found_gpa_column]) and normalize_text(row[found_gpa_column]).lower() in ["通過", "抵免", "pass", "exempt"]) or \
                       (found_credit_column in row and pd.notna(row[found_credit_column]) and normalize_text(row[found_credit_column]).lower() in ["通過", "抵免", "pass", "exempt"]):
                        is_passed_or_exempt_grade = True
                        
                    course_name = "未知科目" 
                    if found_subject_column in row and pd.notna(row[found_subject_column]): 
                        temp_name = normalize_text(row[found_subject_column])
                        # 修改此處：科目名稱長度判斷，放寬為 >= 2 個字
                        if len(temp_name) >= 2 and re.search(r'[\u4e00-\u9fa5]', temp_name): 
                            course_name = temp_name
                        elif not temp_name: 
                            # If subject column is empty, try to infer from adjacent columns if they contain text that looks like a course name
                            try:
                                current_col_idx = df.columns.get_loc(found_subject_column)
                                # Check column to the left
                                if current_col_idx > 0: 
                                    prev_col_name = df.columns[current_col_idx - 1]
                                    if prev_col_name in row and pd.notna(row[prev_col_name]):
                                        temp_name_prev_col = normalize_text(row[prev_col_name])
                                        # 修改此處：相鄰欄位科目名稱長度判斷，放寬為 >= 2 個字
                                        if len(temp_name_prev_col) >= 2 and re.search(r'[\u4e00-\u9fa5]', temp_name_prev_col) and \
                                            not temp_name_prev_col.isdigit() and not re.match(r'^[A-Fa-f][+\-]?$', temp_name_prev_col):
                                            course_name = temp_name_prev_col
                                            
                                # If still "未知科目", check column to the right (less common for subject, but possible)
                                if course_name == "未知科目" and current_col_idx < len(df.columns) - 1:
                                    next_col_name = df.columns[current_col_idx + 1]
                                    if next_col_name in row and pd.notna(row[next_col_name]):
                                        temp_name_next_col = normalize_text(row[next_col_name])
                                        # 修改此處：相鄰欄位科目名稱長度判斷，放寬為 >= 2 個字
                                        if len(temp_name_next_col) >= 2 and re.search(r'[\u4e00-\u9fa5]', temp_name_next_col) and \
                                            not temp_name_next_col.isdigit() and not re.match(r'^[A-Fa-f][+\-]?$', temp_name_next_col):
                                            course_name = temp_name_next_col
                            except Exception:
                                pass
                    
                    # 如果科目名稱還是未知，且學分和 GPA 也無法判斷，可能是無效行，跳過
                    if course_name == "未知科目" and extracted_credit == 0.0 and not extracted_gpa and not is_passed_or_exempt_grade:
                        continue

                    # 嘗試獲取學年度和學期
                    acad_year = ""
                    semester = ""
                    # 優先從識別出的學年學期欄位獲取
                    if found_year_column and found_year_column in row and pd.notna(row[found_year_column]):
                        temp_year = normalize_text(row[found_year_column])
                        if temp_year.isdigit() and (len(temp_year) == 3 or len(temp_year) == 4):
                            acad_year = temp_year
                    # 如果沒有明確的學年欄位，但學期欄位是組合的，從學期欄位提取學年
                    elif found_semester_column and found_semester_column in row and pd.notna(row[found_semester_column]):
                        combined_val = normalize_text(row[found_semester_column])
                        year_match = re.search(r'(\d{3,4})', combined_val)
                        if year_match:
                            acad_year = year_match.group(1)
                    
                    # 針對學期欄位，確保只提取學期部分
                    if found_semester_column and found_semester_column in row and pd.notna(row[found_semester_column]):
                        temp_sem = normalize_text(row[found_semester_column])
                        sem_match = re.search(r'(上|下|春|夏|秋|冬|1|2|3|春季|夏季|秋季|冬季|spring|summer|fall|winter)', temp_sem, re.IGNORECASE)
                        if sem_match:
                            semester = sem_match.group(1)

                    # 如果學年和學期仍然是空的，嘗試從前兩列（如果存在）提取
                    if not acad_year and len(df.columns) > 0 and df.columns[0] in row and pd.notna(row[df.columns[0]]):
                        temp_first_col = normalize_text(row[df.columns[0]])
                        year_match = re.search(r'(\d{3,4})', temp_first_col)
                        if year_match:
                            acad_year = year_match.group(1)
                        if not semester: # If semester still not found, try to extract from first column
                             sem_match = re.search(r'(上|下|春|夏|秋|冬|1|2|3|春季|夏季|秋季|冬季|spring|summer|fall|winter)', temp_first_col, re.IGNORECASE)
                             if sem_match:
                                 semester = sem_match.group(1)

                    if not semester and len(df.columns) > 1 and df.columns[1] in row and pd.notna(row[df.columns[1]]):
                        temp_second_col = normalize_text(row[df.columns[1]])
                        sem_match = re.search(r'(上|下|春|夏|秋|冬|1|2|3|春季|夏季|秋季|冬季|spring|summer|fall|winter)', temp_second_col, re.IGNORECASE)
                        if sem_match:
                            semester = sem_match.group(1)


                    # 判斷是否計入總學分或不及格學分
                    if is_failing_grade:
                        failed_courses.append({
                            "學年度": acad_year,
                            "學期": semester,
                            "科目名稱": course_name, 
                            "學分": extracted_credit, 
                            "GPA": extracted_gpa, 
                            "來源表格": df_idx + 1
                        })
                    elif extracted_credit > 0 or is_passed_or_exempt_grade: 
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
                            if any(cell.strip() != "" for cell in normalized_row):
                                processed_table.append(normalized_row)
                        
                        if not processed_table:
                            st.info(f"頁面 {page_num + 1} 的表格 **{table_idx + 1}** 提取後為空。")
                            continue

                        # 確保表格至少有1行，並且列數合理
                        # 這裡放寬了判斷，只要有數據就嘗試處理，讓 is_grades_table 去判斷是否為成績單
                        if len(processed_table) > 0 and len(processed_table[0]) >= 3: 
                            header_row = processed_table[0]
                            data_rows = processed_table[1:]
                        else:
                            st.info(f"頁面 {page_num + 1} 的表格 {table_idx + 1} 結構不完整或行數不足，已跳過。")
                            continue

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
                                if is_grades_table(df_table):
                                    all_grades_data.append(df_table)
                                    st.success(f"頁面 {page_num + 1} 的表格 {table_idx + 1} 已識別為成績單表格並已處理。")
                                else:
                                    st.info(f"頁面 {page_num + 1} 的表格 {table_idx + 1} (表頭範例: {header_row}) 未識別為成績單表格，已跳過。")
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
