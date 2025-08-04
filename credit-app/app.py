import streamlit as st
import pandas as pd
import pdfplumber
import collections
import re

# --- 全域定義的關鍵字列表 ---
credit_column_keywords = ["學分", "學分數", "學分(GPA)", "學 分", "Credits", "Credit", "學分數(學分)", "總學分"]
subject_column_keywords = ["科目名稱", "課程名稱", "Course Name", "Subject Name", "科目", "課程"]
gpa_column_keywords = ["GPA", "成績", "Grade", "gpa(數值)"]
year_column_keywords = ["學年", "year", "學 年"]
semester_column_keywords = ["學期", "semester", "學 期"]
failing_grades = ["D", "D-", "E", "F", "X", "不通過", "未通過", "不及格"]

# 將所有標頭關鍵字扁平化為一個列表，用於更廣泛的標頭行判斷
# 使用 set 以提高查詢效率，並確保唯一性
all_header_keywords_flat_lower = set([
    k.lower() for k in 
    credit_column_keywords + 
    subject_column_keywords + 
    gpa_column_keywords + 
    year_column_keywords + 
    semester_column_keywords
])


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
        
        # For empty or very short strings, use 'Column_X' format
        if not original_col_cleaned or len(original_col_cleaned) < 2: 
            name_base = "Column"
            current_idx = 1
            # Ensure generated Column_X is unique within unique_columns list
            while f"{name_base}_{current_idx}" in unique_columns:
                current_idx += 1
            name = f"{name_base}_{current_idx}"
        else:
            name = original_col_cleaned
        
        # Handle duplicate names by adding a suffix
        final_name = name
        counter = seen[name]
        while final_name in unique_columns:
            counter += 1
            final_name = f"{name}_{counter}" 
        
        unique_columns.append(final_name)
        seen[name] = counter # Update the max count for this base name

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
        return 0.0, text_clean

    # 嘗試匹配 "GPA 學分" 模式 (例如 "A 2", "C- 3")
    match_gpa_credit = re.match(r'([A-Fa-f][+\-]?)\s*(\d+(\.\d+)?)', text_clean)
    if match_gpa_credit:
        gpa = match_gpa_credit.group(1).upper()
        try:
            credit = float(match_gpa_credit.group(2))
            if 0.0 < credit <= 5.0: # 學分不超過5的限制 (reverted)
                return credit, gpa
        except ValueError:
            pass

    # 嘗試匹配 "學分 GPA" 模式 (例如 "2 A", "3 B-")
    match_credit_gpa = re.match(r'(\d+(\.\d+)?)\s*([A-Fa-f][+\-]?)', text_clean)
    if match_credit_gpa:
        try:
            credit = float(match_credit_gpa.group(1))
            gpa = match_credit_gpa.group(3).upper()
            if 0.0 < credit <= 5.0: # 學分不超過5的限制 (reverted)
                return credit, gpa
        except ValueError:
            pass
            
    # 嘗試只匹配學分 (純數字)
    credit_only_match = re.search(r'(\d+(\.\d+)?)', text_clean)
    if credit_only_match:
        try:
            credit = float(credit_only_match.group(1))
            if 0.0 < credit <= 5.0: # 學分不超過5的限制 (reverted)
                return credit, "" 
        except ValueError:
            pass

    # 嘗試只匹配 GPA (純字母)
    gpa_only_match = re.search(r'([A-Fa-f][+\-]?)', text_clean)
    if gpa_only_match:
        return 0.0, gpa_only_match.group(1).upper()

    return 0.0, ""

def is_grades_table(df):
    """
    判斷一個 DataFrame 是否為有效的成績單表格。
    透過檢查是否存在預期的欄位關鍵字和數據內容模式來判斷。
    """
    if df.empty or len(df.columns) < 3:
        return False

    # Normalize column names for keyword matching
    # 使用 make_unique_columns 處理潛在的重複和空欄位名稱 (already done before calling this)
    normalized_columns = {re.sub(r'\s+', '', col).lower(): col for col in df.columns.tolist()}
    
    # Check for direct header matches first
    has_credit_col_header = any(any(k in norm_col for k in credit_column_keywords) for norm_col in normalized_columns.keys())
    has_gpa_col_header = any(any(k in norm_col for k in gpa_column_keywords) for norm_col in normalized_columns.keys())
    has_subject_col_header = any(any(k in norm_col for k in subject_column_keywords) for norm_col in normalized_columns.keys())
    has_year_col_header = any(any(k in norm_col for k in year_column_keywords) for norm_col in normalized_columns.keys())
    has_semester_col_header = any(any(k in norm_col for k in semester_column_keywords) for norm_col in normalized_columns.keys())

    # If all header keywords are present, it's a strong indicator
    if has_subject_col_header and (has_credit_col_header or has_gpa_col_header) and has_year_col_header and has_semester_col_header:
        return True
    
    # If not all headers are present, check content patterns
    # The thresholds might need fine-tuning based on actual PDF quality
    # We are looking for at least 3 out of 4 essential types to consider it a grades table by content
    
    # Find columns by content patterns - we need at least one of each critical type
    found_year_by_content = False
    found_semester_by_content = False
    found_subject_by_content = False
    found_credit_or_gpa_by_content = False

    sample_rows_df = df.head(min(len(df), 20)) # Use first few rows for sampling

    for col_name in df.columns:
        sample_data = sample_rows_df[col_name].apply(normalize_text).tolist()
        total_sample_count = len(sample_data)
        if total_sample_count == 0:
            continue

        # Year-like column: contains 3 or 4 digit numbers (e.g., 111, 2024)
        if not found_year_by_content:
            year_like_cells = sum(1 for item_str in sample_data if (item_str.isdigit() and (len(item_str) == 3 or len(item_str) == 4)))
            if year_like_cells / total_sample_count >= 0.6: # High confidence
                found_year_by_content = True

        # Semester-like column: contains specific semester keywords
        if not found_semester_by_content:
            semester_like_cells = sum(1 for item_str in sample_data if item_str.lower() in ["上", "下", "春", "夏", "秋", "冬", "1", "2", "3", "春季", "夏季", "秋季", "冬季", "spring", "summer", "fall", "winter"])
            if semester_like_cells / total_sample_count >= 0.6: # High confidence
                found_semester_by_content = True

        # Subject-like column: contains mostly Chinese characters, not just digits/GPA
        if not found_subject_by_content:
            subject_like_cells = sum(1 for item_str in sample_data 
                                     if re.search(r'[\u4e00-\u9fa5]', item_str) and len(item_str) >= 2
                                     and not item_str.isdigit() and not re.match(r'^[A-Fa-f][+\-]?$', item_str)
                                     and not item_str.lower() in ["通過", "抵免", "pass", "exempt", "未知科目"])
            if subject_like_cells / total_sample_count >= 0.4: # Moderate confidence
                found_subject_by_content = True

        # Credit/GPA-like column: contains numbers suitable for credits or grade letters
        if not found_credit_or_gpa_by_content:
            credit_gpa_like_cells = 0
            for item_str in sample_data:
                credit_val, gpa_val = parse_credit_and_gpa(item_str)
                if (0.0 < credit_val <= 5.0) or \
                   (gpa_val and re.match(r'^[A-Fa-f][+\-]?$', gpa_val)) or \
                   (item_str.lower() in ["通過", "抵免", "pass", "exempt"]):
                    credit_gpa_like_cells += 1
            if credit_gpa_like_cells / total_sample_count >= 0.4: # Moderate confidence
                found_credit_or_gpa_by_content = True
    
    # A table is considered a grades table if it has at least one of each crucial column type by content
    if found_year_by_content and found_semester_by_content and found_subject_by_content and found_credit_or_gpa_by_content:
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

    for df_idx, df in enumerate(df_list):
        if df.empty or len(df.columns) < 3: # Skip empty or too small dataframes
            continue
        
        # Dictionary to store identified column names for each role
        identified_columns = {
            "year": None,
            "semester": None,
            "subject": None,
            "credit": None,
            "gpa": None
        }

        # Step 1: Prioritize identifying columns by their content patterns and relative positions
        # Store (column_name, score) for each potential role
        potential_roles_scores = collections.defaultdict(list) # {role: [(col_name, score)]}

        sample_rows_df = df.head(min(len(df), 20)) # Sample first few rows for pattern detection

        for col_name in df.columns:
            sample_data = sample_rows_df[col_name].apply(normalize_text).tolist()
            total_sample_count = len(sample_data)
            if total_sample_count == 0:
                continue

            # Calculate scores for each role based on content
            year_score = sum(1 for item_str in sample_data if (item_str.isdigit() and (len(item_str) == 3 or len(item_str) == 4))) / total_sample_count
            semester_score = sum(1 for item_str in sample_data if item_str.lower() in ["上", "下", "春", "夏", "秋", "冬", "1", "2", "3", "春季", "夏季", "秋季", "冬季", "spring", "summer", "fall", "winter"]) / total_sample_count
            
            credit_gpa_score = 0
            for item_str in sample_data:
                credit_val, gpa_val = parse_credit_and_gpa(item_str)
                if (0.0 < credit_val <= 5.0) or (gpa_val and re.match(r'^[A-Fa-f][+\-]?$', gpa_val)) or (item_str.lower() in ["通過", "抵免", "pass", "exempt"]):
                    credit_gpa_score += 1
            credit_gpa_score /= total_sample_count

            # Subject needs to be distinct from other types
            subject_score = sum(1 for item_str in sample_data 
                                 if re.search(r'[\u4e00-\u9fa5]', item_str) and len(item_str) >= 2
                                 and not item_str.isdigit() and not re.match(r'^[A-Fa-f][+\-]?$', item_str)
                                 and not item_str.lower() in ["通過", "抵免", "pass", "exempt", "未知科目"]
                                 and not any(k in item_str.lower() for k in credit_column_keywords + gpa_column_keywords + year_column_keywords + semester_column_keywords)
                                ) / total_sample_count

            if year_score >= 0.6: potential_roles_scores["year"].append((col_name, year_score))
            if semester_score >= 0.6: potential_roles_scores["semester"].append((col_name, semester_score))
            if credit_gpa_score >= 0.4: potential_roles_scores["credit_gpa"].append((col_name, credit_gpa_score)) # Group credit and gpa for now
            if subject_score >= 0.4: potential_roles_scores["subject"].append((col_name, subject_score))

        # Sort potentials by score (desc) then by column index (asc) to pick the best candidate
        for role in potential_roles_scores:
            potential_roles_scores[role].sort(key=lambda x: (-x[1], df.columns.get_loc(x[0]))) # Higher score first, then earlier column

        # Assign columns based on ranked potentials, prioritizing distinct roles
        # If a column can be both credit and GPA, we'll try to distinguish later.
        
        # Year and Semester are often first and clear
        if potential_roles_scores["year"]:
            identified_columns["year"] = potential_roles_scores["year"][0][0]
        if potential_roles_scores["semester"]:
            identified_columns["semester"] = potential_roles_scores["semester"][0][0]
            # If year and semester are the same column, and it matches year pattern better, prioritize year
            if identified_columns["year"] == identified_columns["semester"]:
                if potential_roles_scores["year"][0][1] > potential_roles_scores["semester"][0][1]:
                    identified_columns["semester"] = None # Let it be found by header if possible

        # Subject column is usually to the left of credit/GPA
        if potential_roles_scores["subject"]:
            identified_columns["subject"] = potential_roles_scores["subject"][0][0]

        # Credit/GPA is tricky, try to pick distinct ones
        credit_gpa_candidates = [cn for cn, _ in potential_roles_scores["credit_gpa"]]
        
        # Try to find a dedicated credit column
        found_credit_via_content = False
        for c in credit_gpa_candidates:
            # Check if this column's header contains credit keywords
            norm_col_name = re.sub(r'\s+', '', c).lower()
            if any(k in norm_col_name for k in credit_column_keywords):
                identified_columns["credit"] = c
                found_credit_via_content = True
                break
            # Or if it contains mostly numbers and less letter grades
            sample_data = sample_rows_df[c].apply(normalize_text).tolist()
            num_only_count = sum(1 for item_str in sample_data if re.match(r'^\d+(\.\d+)?$', item_str) and (0.0 < float(item_str) <= 5.0))
            if num_only_count / total_sample_count >= 0.5: # If mostly numbers fitting credit pattern
                 if identified_columns["credit"] is None: # Pick the first one
                     identified_columns["credit"] = c
                     found_credit_via_content = True
        
        # Try to find a dedicated GPA column, distinct from credit
        found_gpa_via_content = False
        for c in credit_gpa_candidates:
            if c == identified_columns["credit"]: continue # Don't re-use the credit column
            # Check if this column's header contains GPA keywords
            norm_col_name = re.sub(r'\s+', '', c).lower()
            if any(k in norm_col_name for k in gpa_column_keywords):
                identified_columns["gpa"] = c
                found_gpa_via_content = True
                break
            # Or if it contains mostly letter grades
            sample_data = sample_rows_df[c].apply(normalize_text).tolist()
            gpa_letter_count = sum(1 for item_str in sample_data if re.match(r'^[A-Fa-f][+\-]?$', item_str))
            if gpa_letter_count / total_sample_count >= 0.5: # If mostly letter grades
                if identified_columns["gpa"] is None: # Pick the first one
                    identified_columns["gpa"] = c
                    found_gpa_via_content = True

        # Fallback to general credit/GPA if distinct columns not found (take first from candidates)
        if identified_columns["credit"] is None and credit_gpa_candidates:
            identified_columns["credit"] = credit_gpa_candidates[0]
        if identified_columns["gpa"] is None and len(credit_gpa_candidates) > 1 and identified_columns["credit"] != credit_gpa_candidates[1]:
            identified_columns["gpa"] = credit_gpa_candidates[1] # Try second candidate if different

        # Step 2: Use header keywords as a strong confirmation or fallback if content detection was weak
        # For each role, if not found by content, or if content detection was ambiguous, check header keywords
        normalized_df_columns = {re.sub(r'\s+', '', col_name).lower(): col_name for col_name in df.columns}

        # Override or confirm identified_columns based on header keywords
        for role, keywords in [
            ("year", year_column_keywords),
            ("semester", semester_column_keywords),
            ("subject", subject_column_keywords),
            ("credit", credit_column_keywords),
            ("gpa", gpa_column_keywords)
        ]:
            if identified_columns[role] is None or \
               (identified_columns[role] is not None and not any(k in re.sub(r'\s+', '', identified_columns[role]).lower() for k in keywords) and len(keywords) > 0):
                # If column not found, or found but its header doesn't match keyword (suggests content match might be weak)
                for k in keywords:
                    for norm_col_key, original_col_name in normalized_df_columns.items():
                        if k in norm_col_key:
                            # Prioritize header match, especially if no strong content match
                            identified_columns[role] = original_col_name
                            break
                    if identified_columns[role]: break
        
        found_year_column = identified_columns["year"]
        found_semester_column = identified_columns["semester"]
        found_subject_column = identified_columns["subject"]
        found_credit_column = identified_columns["credit"]
        found_gpa_column = identified_columns["gpa"]

        # Proceed only if essential columns are found (year, semester, subject, credit/gpa)
        if found_year_column and found_semester_column and found_subject_column and (found_credit_column or found_gpa_column):
            try:
                for row_idx, row in df.iterrows():
                    # 偵錯輸出：顯示原始資料列
                    st.info(f"--- 處理表格 {df_idx + 1}, 第 {row_idx + 1} 行 ---")
                    st.info(f"原始資料列內容: {[normalize_text(str(cell)) for cell in row.tolist()]}")
                    st.info(f"識別到的學年欄位: '{found_year_column}' (內容: {row.get(found_year_column, '') if found_year_column else 'N/A'}), 學期欄位: '{found_semester_column}' (內容: {row.get(found_semester_column, '') if found_semester_column else 'N/A'})")
                    st.info(f"識別到的科目欄位: '{found_subject_column}' (內容: {row.get(found_subject_column, '') if found_subject_column else 'N/A'}), 學分欄位: '{found_credit_column}' (內容: {row.get(found_credit_column, '') if found_credit_column else 'N/A'}), GPA欄位: '{found_gpa_column}' (內容: {row.get(found_gpa_column, '') if found_gpa_column else 'N/A'})")

                    extracted_credit = 0.0
                    extracted_gpa = ""

                    # --- 新增的標頭行內容判斷邏輯 ---
                    row_content = [normalize_text(str(cell)) for cell in row]
                    is_header_row_content = False
                    header_keyword_matches = 0
                    for cell_val in row_content:
                        normalized_cell_val = normalize_text(cell_val).lower()
                        # 檢查單元格內容是否精確匹配任何一個已知的標頭關鍵字
                        if normalized_cell_val in all_header_keywords_flat_lower:
                            header_keyword_matches += 1
                    
                    # 如果一行中匹配到的標頭關鍵字達到一定數量，就判斷為標頭行
                    # 這個閾值可以根據實際的成績單格式調整，3-4 個通常是一個不錯的起點
                    if header_keyword_matches >= 3: 
                        is_header_row_content = True

                    # Skip rows that appear to be empty, header-like or just administrative text
                    if all(cell == "" for cell in row_content) or \
                       is_header_row_content or \
                       any("體育室" in cell or "本表僅供查詢" in cell or "學號" in cell or "勞作" in cell for cell in row_content):
                        st.info("該行被判斷為空行、標頭行或行政性文字，已跳過。")
                        continue

                    # Extract from credit column first, it might contain both
                    if found_credit_column in row and pd.notna(row[found_credit_column]):
                        extracted_credit, extracted_gpa_from_credit_col = parse_credit_and_gpa(row[found_credit_column])
                        if extracted_gpa_from_credit_col and not extracted_gpa: # Prioritize GPA from dedicated column if available
                            extracted_gpa = extracted_gpa_from_credit_col
                    
                    # Then extract/override GPA from dedicated GPA column if it exists
                    if found_gpa_column and found_gpa_column in row and pd.notna(row[found_gpa_column]):
                        gpa_from_gpa_col_raw = normalize_text(row[found_gpa_column])
                        parsed_credit_from_gpa_col, parsed_gpa_from_gpa_col = parse_credit_and_gpa(gpa_from_gpa_col_raw)
                        
                        if parsed_gpa_from_gpa_col: # Use GPA from dedicated GPA column if found
                            extracted_gpa = parsed_gpa_from_gpa_col.upper()
                        
                        # Only update extracted_credit if it's currently 0 and a valid credit is found in GPA column
                        if parsed_credit_from_gpa_col > 0 and extracted_credit == 0.0:
                            extracted_credit = parsed_credit_from_gpa_col
                    
                    # Final check for credit value to ensure it adheres to the max 5 credit rule
                    if extracted_credit is None or not (0.0 < extracted_credit <= 5.0): # Reverted to 0.0 < credit <= 5.0
                        extracted_credit = 0.0

                    is_failing_grade = False
                    if extracted_gpa:
                        gpa_clean = re.sub(r'[+\-]', '', extracted_gpa).upper()
                        # Check for failing letter grades or numeric grades below 60
                        if gpa_clean in failing_grades or (gpa_clean.isdigit() and float(gpa_clean) < 60):
                            is_failing_grade = True
                        elif gpa_clean.replace('.', '', 1).isdigit() and float(gpa_clean) < 60: # Handle float grades if any
                            is_failing_grade = True
                    
                    is_passed_or_exempt_grade = False
                    # Check if the grade is explicitly "通過", "抵免", etc. in either credit or GPA column
                    if (found_gpa_column and found_gpa_column in row and pd.notna(row[found_gpa_column]) and normalize_text(row[found_gpa_column]).lower() in ["通過", "抵免", "pass", "exempt"]) or \
                       (found_credit_column and found_credit_column in row and pd.notna(row[found_credit_column]) and normalize_text(row[found_credit_column]).lower() in ["通過", "抵免", "pass", "exempt"]):
                        is_passed_or_exempt_grade = True
                        
                    course_name = "" # Initialize as empty string
                    if found_subject_column in row and pd.notna(row[found_subject_column]):
                        temp_name = normalize_text(row[found_subject_column])
                        # Only accept as subject name if it's reasonably long and contains Chinese characters, not just numbers or GPA
                        # Relaxed len(temp_name) >= 1 to allow for very short course names if necessary
                        if len(temp_name) >= 1 and re.search(r'[\u4e00-\u9fa5]', temp_name) and \
                           not temp_name.isdigit() and not re.match(r'^[A-Fa-f][+\-]?$', temp_name) and \
                           not temp_name.lower() in ["通過", "抵免", "pass", "exempt", "未知科目"] and \
                           not any(kw in temp_name for kw in ["學年度", "學期", "選課代號", "科目名稱", "學分", "GPA", "本表", "備註"]): # Filter out header-like or administrative text
                            course_name = temp_name
                        # If subject cell is empty or filtered out, try adjacent columns if they look like subject names
                        else: 
                            current_col_idx = df.columns.get_loc(found_subject_column)
                            # Check column to the left
                            if current_col_idx > 0:
                                prev_col_name = df.columns[current_col_idx - 1]
                                if prev_col_name in row and pd.notna(row[prev_col_name]):
                                    temp_name_prev_col = normalize_text(row[prev_col_name])
                                    if len(temp_name_prev_col) >= 1 and re.search(r'[\u4e00-\u9fa5]', temp_name_prev_col) and \
                                        not temp_name_prev_col.isdigit() and not re.match(r'^[A-Fa-f][+\-]?$', temp_name_prev_col) and \
                                        not any(kw in temp_name_prev_col for kw in ["學年度", "學期", "選課代號", "科目名稱", "學分", "GPA"]):
                                        course_name = temp_name_prev_col
                                        
                            # If still empty, check column to the right
                            if not course_name and current_col_idx < len(df.columns) - 1:
                                next_col_name = df.columns[current_col_idx + 1]
                                if next_col_name in row and pd.notna(row[next_col_name]):
                                    temp_name_next_col = normalize_text(row[next_col_name])
                                    if len(temp_name_next_col) >= 1 and re.search(r'[\u4e00-\u9fa5]', temp_name_next_col) and \
                                        not temp_name_next_col.isdigit() and not re.match(r'^[A-Fa-f][+\-]?$', temp_name_next_col) and \
                                        not any(kw in temp_name_next_col for kw in ["學年度", "學期", "選課代號", "科目名稱", "學分", "GPA"]):
                                        course_name = temp_name_next_col

                    # If it's still an empty course_name and doesn't have valid credit/GPA, skip this row
                    if not course_name and extracted_credit == 0.0 and not extracted_gpa and not is_passed_or_exempt_grade:
                        st.info("該行沒有識別到科目名稱、有效學分或成績，已跳過。")
                        continue
                    
                    # If course_name is still empty, label it as "未知科目"
                    if not course_name:
                        course_name = "未知科目"


                    # Extract academic year and semester
                    acad_year = ""
                    semester = ""
                    if found_year_column in row and pd.notna(row[found_year_column]):
                        temp_year = normalize_text(row[found_year_column])
                        year_match = re.search(r'(\d{3,4})', temp_year)
                        if year_match:
                            acad_year = year_match.group(1)
                    
                    if found_semester_column in row and pd.notna(row[found_semester_column]):
                        temp_sem = normalize_text(row[found_semester_column])
                        sem_match = re.search(r'(上|下|春|夏|秋|冬|1|2|3|春季|夏季|秋季|冬季|spring|summer|fall|winter)', temp_sem, re.IGNORECASE)
                        if sem_match:
                            semester = sem_match.group(1)

                    # Fallback for year/semester if not found in dedicated columns (e.g., if they are in the first few generic columns)
                    if not acad_year and len(df.columns) > 0 and df.columns[0] in row and pd.notna(row[df.columns[0]]):
                        temp_first_col = normalize_text(row[df.columns[0]])
                        year_match = re.search(r'(\d{3,4})', temp_first_col)
                        if year_match:
                            acad_year = year_match.group(1)
                        if not semester:
                             sem_match = re.search(r'(上|下|春|夏|秋|冬|1|2|3|春季|夏季|秋季|冬季|spring|summer|fall|winter)', temp_first_col, re.IGNORECASE)
                             if sem_match:
                                 semester = sem_match.group(1)

                    if not semester and len(df.columns) > 1 and df.columns[1] in row and pd.notna(row[df.columns[1]]):
                        temp_second_col = normalize_text(row[df.columns[1]])
                        sem_match = re.search(r'(上|下|春|夏|秋|冬|1|2|3|春季|夏季|秋季|冬季|spring|summer|fall|winter)', temp_second_col, re.IGNORECASE)
                        if sem_match:
                            semester = sem_match.group(1)
                    
                    # 偵錯輸出：顯示解析結果
                    st.info(f"解析結果: 科目名稱='{course_name}', 學分='{extracted_credit}', GPA='{extracted_gpa}', 學年='{acad_year}', 學期='{semester}', 是否不及格='{is_failing_grade}'")

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
            st.info(f"頁面 {df_idx + 1} 的表格未能識別為成績單表格 (缺少必要的 學年/學期/科目名稱/學分/GPA 欄位)。已偵測到的欄位: 學年='{found_year_column}', 學期='{found_semester_column}', 科目名稱='{found_subject_column}', 學分='{found_credit_column}', GPA='{found_gpa_column}'")
            
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

                # 調整策略：使用 'text' 策略，並進一步調整 text_tolerance, snap_tolerance, join_tolerance
                # 這些值是為了更好地處理手機掃描或生成的不規則 PDF 表格
                table_settings = {
                    "vertical_strategy": "text", 
                    "horizontal_strategy": "text", 
                    "snap_tolerance": 15,  # 為了更好的手機檔案偵測，稍微增大，允許文字與線條間隔更大
                    "join_tolerance": 15,  # 為了更好的手機檔案偵測，稍微增大，允許線條斷裂更長
                    "edge_min_length": 3, 
                    "text_tolerance": 8,  # 為了更好的手機檔案偵測，稍微增大，允許文字對齊偏差更大
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
                            # Filter out rows that are entirely empty after normalization
                            if any(cell.strip() != "" for cell in normalized_row):
                                processed_table.append(normalized_row)
                        
                        if not processed_table:
                            st.info(f"頁面 {page_num + 1} 的表格 **{table_idx + 1}** 提取後為空或全為空白行。")
                            continue
                        
                        df_table_to_add = None

                        # --- Attempt 1: Assume first row is header if it strongly looks like one ---
                        if len(processed_table) > 1:
                            potential_header_row = processed_table[0]
                            # Create a temporary DataFrame to test if this looks like a grades table header
                            # Use generic columns for the temp df, then check if its first row (which is the actual potential header) contains keywords
                            max_cols_temp = max(len(cell_list) for cell_list in processed_table) # Get max columns from all processed rows
                            temp_generic_columns = make_unique_columns([f"TempCol_{i+1}" for i in range(max_cols_temp)])
                            
                            # Ensure potential_header_row has enough elements to match temp_generic_columns
                            padded_header_row = potential_header_row + [''] * (max_cols_temp - len(potential_header_row))

                            temp_df_for_header_check = pd.DataFrame([padded_header_row], columns=temp_generic_columns)
                            
                            # Check if temp_df_for_header_check's *content* (i.e., the first row) contains header keywords
                            # Normalizing columns for keyword search
                            temp_normalized_header_content = {re.sub(r'\s+', '', cell).lower(): cell for cell in padded_header_row}
                            
                            has_credit_kw = any(any(k in cell for k in credit_column_keywords) for cell in temp_normalized_header_content.keys())
                            has_gpa_kw = any(any(k in cell for k in gpa_column_keywords) for cell in temp_normalized_header_content.keys()) # Added GPA keyword check
                            has_subject_kw = any(any(k in cell for k in subject_column_keywords) for cell in temp_normalized_header_content.keys())
                            has_year_kw = any(any(k in cell for k in year_column_keywords) for cell in temp_normalized_header_content.keys())
                            has_semester_kw = any(any(k in cell for k in semester_column_keywords) for cell in temp_normalized_header_content.keys())

                            if has_subject_kw and (has_credit_kw or has_gpa_kw) and has_year_kw and has_semester_kw: # Strong header match
                                temp_unique_columns = make_unique_columns(potential_header_row)
                                temp_data_rows = processed_table[1:]

                                num_cols_for_df = len(temp_unique_columns)
                                cleaned_temp_data_rows = []
                                for row in temp_data_rows:
                                    if len(row) > num_cols_for_df:
                                        cleaned_temp_data_rows.append(row[:num_cols_for_df])
                                    elif len(row) < num_cols_for_df: 
                                        cleaned_temp_data_rows.append(row + [''] * (num_cols_for_df - len(row)))
                                    else:
                                        cleaned_temp_data_rows.append(row)

                                if cleaned_temp_data_rows:
                                    try:
                                        df_table_with_assumed_header = pd.DataFrame(cleaned_temp_data_rows, columns=temp_unique_columns)
                                        # Double check if the DataFrame with this header looks like a grades table
                                        if is_grades_table(df_table_with_assumed_header):
                                            df_table_to_add = df_table_with_assumed_header
                                            st.success(f"頁面 {page_num + 1} 的表格 {table_idx + 1} 已識別為成績單表格 (帶有偵測到的標頭)。")
                                    except Exception as e_df_temp:
                                        st.warning(f"頁面 {page_num + 1} 表格 {table_idx + 1} 嘗試用第一行作標頭轉換為 DataFrame 時發生錯誤: `{e_df_temp}`。將嘗試將所有行作為數據。")
                                else:
                                    st.info(f"頁面 {page_num + 1} 的表格 {table_idx + 1} 第一行被識別為標頭但無數據行，將嘗試將所有行作為數據。")
                        
                        # --- Attempt 2: Treat all rows as data (generic columns) if Attempt 1 failed or was not applicable ---
                        if df_table_to_add is None:
                            max_cols = max(len(row) for row in processed_table)
                            generic_columns = make_unique_columns([f"Column_{i+1}" for i in range(max_cols)])

                            cleaned_all_rows_data = []
                            for row in processed_table:
                                if len(row) > max_cols:
                                    cleaned_all_rows_data.append(row[:max_cols])
                                elif len(row) < max_cols:
                                    cleaned_all_rows_data.append(row + [''] * (max_cols - len(row)))
                                else:
                                    cleaned_all_rows_data.append(row)
                            
                            if cleaned_all_rows_data:
                                try:
                                    df_table_all_data = pd.DataFrame(cleaned_all_rows_data, columns=generic_columns)
                                    if is_grades_table(df_table_all_data):
                                        df_table_to_add = df_table_all_data
                                        st.success(f"頁面 {page_num + 1} 的表格 {table_idx + 1} 已識別為成績單表格 (所有行皆為數據，使用通用標頭)。")
                                    else:
                                        st.info(f"頁面 {page_num + 1} 的表格 {table_idx + 1} 未能識別為成績單表格，已跳過。")
                                except Exception as e_df_all:
                                    st.error(f"頁面 {page_num + 1} 表格 {table_idx + 1} 嘗試用所有行作數據轉換為 DataFrame 時發生錯誤: `{e_df_all}`")
                            else:
                                st.info(f"頁面 {page_num + 1} 的表格 **{table_idx + 1}** 沒有有效數據行。")

                        if df_table_to_add is not None:
                            all_grades_data.append(df_table_to_add)

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
            st.markdown("---")
            st.markdown("## ⚙️ 偵錯資訊 (Debug Info)")
            st.info("以下是程式碼處理每行數據的詳細過程，幫助您理解學分計算和課程識別的狀況。")
            st.info("您上傳的原始表格內容將會顯示，以及程式碼如何解析各個欄位。")
            st.info("如果您發現有誤，請根據這些資訊告知我具體是哪個表格的哪一行、哪個欄位有問題。")
            st.info("--- 偵錯訊息結束 ---") # 添加這行以明確區分偵錯輸出

            total_credits, calculated_courses, failed_courses = calculate_total_credits(extracted_dfs)

            st.markdown("---")
            st.markdown("## ✅ 查詢結果") 
            st.markdown(f"目前總學分: <span style='color:green; font-size: 24px;'>**{total_credits:.2f}**</span>", unsafe_allow_html=True)
            
            target_credits = st.number_input("輸入您的目標學分 (例如：128)", min_value=0.0, value=128.0, step=1.0, 
                                            help="您可以設定一個畢業學分目標，工具會幫您計算還差多少學分。")
            
            credit_difference = target_credits - total_credits
            if credit_difference > 0:
                st.write(f"距離畢業所需學分 (共{target_credits:.0f}學分) 還差 **{credit_difference:.2f}**")
            elif credit_difference < 0:
                st.write(f"已超越畢業學分 (共{target_credits:.0f}學分) **{abs(credit_difference):.2f}**")
            else:
                st.write(f"已達到畢業所需學分 (共{target_credits:.0f}學分) **0.00**")


            st.markdown("---")
            st.markdown("### 📚 通過的課程列表") 
            if calculated_courses:
                courses_df = pd.DataFrame(calculated_courses)
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
                st.info("這些科目因成績不及格 ('D', 'E', 'F' 等) 而未計入總學分。")

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
