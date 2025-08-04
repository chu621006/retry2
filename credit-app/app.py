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
        return 0.0, text_clean

    # 嘗試匹配 "GPA 學分" 模式 (例如 "A 2", "C- 3")
    match_gpa_credit = re.match(r'([A-Fa-f][+\-]?)\s*(\d+(\.\d+)?)', text_clean)
    if match_gpa_credit:
        gpa = match_gpa_credit.group(1).upper()
        try:
            credit = float(match_gpa_credit.group(2))
            [cite_start]if 0.0 < credit <= 5.0: # 學分不超過5的限制 [cite: 3]
                return credit, gpa
        except ValueError:
            pass

    # 嘗試匹配 "學分 GPA" 模式 (例如 "2 A", "3 B-")
    match_credit_gpa = re.match(r'(\d+(\.\d+)?)\s*([A-Fa-f][+\-]?)', text_clean)
    if match_credit_gpa:
        try:
            credit = float(match_credit_gpa.group(1))
            gpa = match_credit_gpa.group(3).upper()
            [cite_start]if 0.0 < credit <= 5.0: # 學分不超過5的限制 [cite: 3]
                return credit, gpa
        except ValueError:
            pass
            
    # 嘗試只匹配學分 (純數字)
    credit_only_match = re.search(r'(\d+(\.\d+)?)', text_clean)
    if credit_only_match:
        try:
            credit = float(credit_only_match.group(1))
            [cite_start]if 0.0 < credit <= 5.0: # 學分不超過5的限制 [cite: 3]
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
    # [cite_start]使用 make_unique_columns 處理潛在的重複和空欄位名稱 [cite: 4]
    df.columns = make_unique_columns(df.columns.tolist())
    normalized_columns = {re.sub(r'\s+', '', col).lower(): col for col in df.columns.tolist()}
    
    [cite_start]credit_keywords = ["學分", "credits", "credit", "學分數"] [cite: 4]
    [cite_start]gpa_keywords = ["gpa", "成績", "grade", "gpa(數值)"] [cite: 4]
    [cite_start]subject_keywords = ["科目名稱", "課程名稱", "coursename", "subjectname", "科目", "課程"] [cite: 4]
    [cite_start]year_keywords = ["學年", "year"] [cite: 4]
    [cite_start]semester_keywords = ["學期", "semester"] [cite: 4]

    # Check for direct header matches first
    [cite_start]has_credit_col_header = any(any(k in norm_col for k in credit_keywords) for norm_col in normalized_columns.keys()) [cite: 4]
    [cite_start]has_gpa_col_header = any(any(k in norm_col for k in gpa_keywords) for norm_col in normalized_columns.keys()) [cite: 4]
    [cite_start]has_subject_col_header = any(any(k in norm_col for k in subject_keywords) for norm_col in normalized_columns.keys()) [cite: 4]
    [cite_start]has_year_col_header = any(any(k in norm_col for k in year_keywords) for norm_col in normalized_columns.keys()) [cite: 4]
    [cite_start]has_semester_col_header = any(any(k in norm_col for k in semester_keywords) for norm_col in normalized_columns.keys()) [cite: 5]

    # [cite_start]滿足所有關鍵字標頭的表格，很可能是成績單表格 [cite: 5]
    [cite_start]if has_subject_col_header and (has_credit_col_header or has_gpa_col_header) and has_year_col_header and has_semester_col_header: [cite: 5]
        return True
    
    # [cite_start]如果沒有直接的標頭匹配，檢查內容模式 [cite: 5]
    [cite_start]potential_subject_cols = [] [cite: 5]
    [cite_start]potential_credit_gpa_cols = [] [cite: 5]
    [cite_start]potential_year_cols = [] [cite: 5]
    [cite_start]potential_semester_cols = [] [cite: 5]

    # [cite_start]採樣前幾行數據來判斷欄位類型 [cite: 5]
    [cite_start]sample_rows_df = df.head(min(len(df), 20)) [cite: 5]

    [cite_start]for col_name in df.columns: [cite: 5]
        [cite_start]sample_data = sample_rows_df[col_name].apply(normalize_text).tolist() [cite: 6]
        [cite_start]total_sample_count = len(sample_data) [cite: 6]
        if total_sample_count == 0:
            continue

        # [cite_start]Subject-like column: contains mostly Chinese characters, not just digits/GPA [cite: 6]
        subject_like_cells = sum(1 for item_str in sample_data 
                                 if re.search(r'[\u4e00-\u9fa5]', item_str) and len(item_str) >= 2
                                 and not item_str.isdigit() and not re.match(r'^[A-Fa-f][+\-]?$', item_str)
                                 and not item_str.lower() in ["通過", "抵免", "pass", "exempt", "未知科目"])
        [cite_start]if subject_like_cells / total_sample_count >= 0.4: [cite: 6]
            potential_subject_cols.append(col_name)

        # [cite_start]Credit/GPA-like column: contains numbers suitable for credits or grade letters [cite: 6]
        [cite_start]credit_gpa_like_cells = 0 [cite: 6]
        [cite_start]for item_str in sample_data: [cite: 6]
            [cite_start]credit_val, gpa_val = parse_credit_and_gpa(item_str) [cite: 6]
            [cite_start]if (0.0 < credit_val <= 5.0) or \ [cite: 7]
               (gpa_val and re.match(r'^[A-Fa-f][+\-]?$', gpa_val)[cite_start]) or \ [cite: 7]
               (item_str.lower() [cite_start]in ["通過", "抵免", "pass", "exempt"]): [cite: 7]
                [cite_start]credit_gpa_like_cells += 1 [cite: 7]
        [cite_start]if credit_gpa_like_cells / total_sample_count >= 0.4: [cite: 7]
            potential_credit_gpa_cols.append(col_name)

        # [cite_start]Year-like column: contains 3 or 4 digit numbers (e.g., 111, 2024) [cite: 7]
        year_like_cells = sum(1 for item_str in sample_data 
                                  [cite_start]if (item_str.isdigit() and (len(item_str) == 3 or len(item_str) == 4))) [cite: 7]
        [cite_start]if year_like_cells / total_sample_count >= 0.6: [cite: 7]
            potential_year_cols.append(col_name)

        # [cite_start]Semester-like column: contains specific semester keywords [cite: 7]
        semester_like_cells = sum(1 for item_str in sample_data 
                                  [cite_start]if item_str.lower() in ["上", "下", "春", "夏", "秋", "冬", "1", "2", "3", "春季", "夏季", "秋季", "冬季", "spring", "summer", "fall", "winter"]) [cite: 8]
        [cite_start]if semester_like_cells / total_sample_count >= 0.6: [cite: 8]
            potential_semester_cols.append(col_name)

    # [cite_start]A table is considered a grades table if it has at least one of each crucial column type [cite: 8]
    [cite_start]if potential_subject_cols and potential_credit_gpa_cols and potential_year_cols and potential_semester_cols: [cite: 8]
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

    [cite_start]credit_column_keywords = ["學分", "學分數", "學分(GPA)", "學 分", "Credits", "Credit", "學分數(學分)", "總學分"] [cite: 9]
    [cite_start]subject_column_keywords = ["科目名稱", "課程名稱", "Course Name", "Subject Name", "科目", "課程"] [cite: 9]
    [cite_start]gpa_column_keywords = ["GPA", "成績", "Grade", "gpa(數值)"] [cite: 9]
    [cite_start]year_column_keywords = ["學年", "year", "學 年"] [cite: 9]
    [cite_start]semester_column_keywords = ["學期", "semester", "學 期"] [cite: 10]
    
    [cite_start]failing_grades = ["D", "D-", "E", "F", "X", "不通過", "未通過", "不及格"] [cite: 10]

    [cite_start]for df_idx, df in enumerate(df_list): [cite: 10]
        [cite_start]if df.empty or len(df.columns) < 3: # Skip empty or too small dataframes [cite: 10]
            continue
        
        # [cite_start]確保 DataFrame 的欄位名稱是唯一的 [cite: 11]
        [cite_start]df.columns = make_unique_columns(df.columns.tolist()) [cite: 11]

        [cite_start]found_credit_column = None [cite: 11]
        [cite_start]found_subject_column = None [cite: 11]
        [cite_start]found_gpa_column = None [cite: 11]
        [cite_start]found_year_column = None [cite: 11]
        [cite_start]found_semester_column = None [cite: 11]
        
        # [cite_start]Create a normalized map for column names to find headers [cite: 11]
        [cite_start]normalized_df_columns = {re.sub(r'\s+', '', col_name).lower(): col_name for col_name in df.columns} [cite: 12]
        
        # [cite_start]Try to find columns by header names first [cite: 12]
        [cite_start]for k in credit_column_keywords: [cite: 12]
            [cite_start]if any(k in norm_col for norm_col in normalized_df_columns.keys()): [cite: 12]
                [cite_start]for norm_col_key, original_col_name in normalized_df_columns.items(): [cite: 12]
                    [cite_start]if k in norm_col_key: [cite: 13]
                        [cite_start]found_credit_column = original_col_name [cite: 13]
                        break
            [cite_start]if found_credit_column: break [cite: 13]
        
        [cite_start]for k in subject_column_keywords: [cite: 13]
            [cite_start]if any(k in norm_col for norm_col in normalized_df_columns.keys()): [cite: 14]
                [cite_start]for norm_col_key, original_col_name in normalized_df_columns.items(): [cite: 14]
                    [cite_start]if k in norm_col_key: [cite: 14]
                        [cite_start]found_subject_column = original_col_name [cite: 15]
                        break
            [cite_start]if found_subject_column: break [cite: 15]

        [cite_start]for k in gpa_column_keywords: [cite: 15]
            [cite_start]if any(k in norm_col for norm_col in normalized_df_columns.keys()): [cite: 15]
                [cite_start]for norm_col_key, original_col_name in normalized_df_columns.items(): [cite: 15]
                    [cite_start]if k in norm_col_key: [cite: 16]
                        [cite_start]found_gpa_column = original_col_name [cite: 16]
                        break
            [cite_start]if found_gpa_column: break [cite: 16]

        [cite_start]for k in year_column_keywords: [cite: 16]
            [cite_start]if any(k in norm_col for norm_col in normalized_df_columns.keys()): [cite: 16]
                [cite_start]for norm_col_key, original_col_name in normalized_df_columns.items(): [cite: 17]
                    [cite_start]if k in norm_col_key: [cite: 17]
                        [cite_start]found_year_column = original_col_name [cite: 17]
                        break
            [cite_start]if found_year_column: break [cite: 17]
        
        [cite_start]for k in semester_column_keywords: [cite: 18]
            [cite_start]if any(k in norm_col for norm_col in normalized_df_columns.keys()): [cite: 18]
                [cite_start]for norm_col_key, original_col_name in normalized_df_columns.items(): [cite: 18]
                    [cite_start]if k in norm_col_key: [cite: 18]
                        [cite_start]found_semester_column = original_col_name [cite: 19]
                        break
            [cite_start]if found_semester_column: break [cite: 19]

        # [cite_start]If headers not found, try to infer based on content patterns (potential_cols) [cite: 19]
        [cite_start]potential_credit_cols = [] [cite: 19]
        [cite_start]potential_subject_cols = [] [cite: 19]
        [cite_start]potential_gpa_cols = [] [cite: 19]
        [cite_start]potential_year_cols = [] [cite: 20]
        [cite_start]potential_semester_cols = [] [cite: 20]

        [cite_start]sample_rows_df = df.head(min(len(df), 20)) [cite: 20]

        [cite_start]for col_name in df.columns: [cite: 20]
            [cite_start]sample_data = sample_rows_df[col_name].apply(normalize_text).tolist() [cite: 21]
            [cite_start]total_sample_count = len(sample_data) [cite: 21]
            if total_sample_count == 0:
                continue

            [cite_start]credit_vals_found = 0 [cite: 21]
            [cite_start]for item_str in sample_data: [cite: 21]
                [cite_start]credit_val, _ = parse_credit_and_gpa(item_str) [cite: 21]
                [cite_start]if 0.0 < credit_val <= 5.0: # Credits usually between 0.5 and 5 [cite: 21]
                    [cite_start]credit_vals_found += 1 [cite: 21]
            [cite_start]if credit_vals_found / total_sample_count >= 0.4: [cite: 22]
                potential_credit_cols.append(col_name)

            [cite_start]subject_vals_found = 0 [cite: 22]
            [cite_start]for item_str in sample_data: [cite: 22]
                # [cite_start]Subject should contain Chinese characters, be reasonably long, and not look like just a number or GPA [cite: 22]
                [cite_start]if re.search(r'[\u4e00-\u9fa5]', item_str) and len(item_str) >= 2 and not item_str.isdigit() and not re.match(r'^[A-Fa-f][+\-]?$', item_str) and not item_str.lower() in ["通過", "抵免", "pass", "exempt", "未知科目"]: [cite: 23]
                    [cite_start]subject_vals_found += 1 [cite: 23]
            [cite_start]if subject_vals_found / total_sample_count >= 0.4: [cite: 23]
                potential_subject_cols.append(col_name)

            [cite_start]gpa_vals_found = 0 [cite: 23]
            [cite_start]for item_str in sample_data: [cite: 24]
                # GPA can be letter grades, or sometimes numerical (e.g., 80, 75). [cite_start]Also '通過' etc. [cite: 24, 25]
                [cite_start]if re.match(r'^[A-Fa-f][+\-]' , item_str) or (item_str.isdigit() and len(item_str) <=3) or item_str.lower() in ["通過", "抵免", "pass", "exempt"]: [cite: 25]
                    [cite_start]gpa_vals_found += 1 [cite: 25]
            [cite_start]if gpa_vals_found / total_sample_count >= 0.4: [cite: 25]
                potential_gpa_cols.append(col_name)

            [cite_start]year_vals_found = 0 [cite: 25]
            [cite_start]for item_str in sample_data: [cite: 26]
                # [cite_start]Year typically 3 or 4 digits [cite: 26]
                [cite_start]if (item_str.isdigit() and (len(item_str) == 3 or len(item_str) == 4)): [cite: 26]
                    [cite_start]year_vals_found += 1 [cite: 26]
            [cite_start]if year_vals_found / total_sample_count >= 0.6: [cite: 27]
                potential_year_cols.append(col_name)

            semester_like_cells = sum(1 for item_str in sample_data 
                                  [cite_start]if item_str.lower() in ["上", "下", "春", "夏", "秋", "冬", "1", "2", "3", "春季", "夏季", "秋季", "冬季", "spring", "summer", "fall", "winter"]) [cite: 27]
            [cite_start]if semester_like_cells / total_sample_count >= 0.6: [cite: 28]
                potential_semester_cols.append(col_name)

        # [cite_start]Prioritize columns based on their typical order in a transcript if headers not found [cite: 28]
        [cite_start]if not found_year_column and potential_year_cols: [cite: 28]
            [cite_start]found_year_column = sorted(potential_year_cols, key=lambda x: df.columns.get_loc(x))[0] [cite: 28]
        [cite_start]if not found_semester_column and potential_semester_cols: [cite: 28]
            [cite_start]if found_year_column: # Semester is usually after year [cite: 29]
                [cite_start]year_col_idx = df.columns.get_loc(found_year_column) [cite: 29]
                [cite_start]candidates = [col for col in potential_semester_cols if df.columns.get_loc(col) > year_col_idx] [cite: 29]
                [cite_start]if candidates: [cite: 29]
                    [cite_start]found_semester_column = sorted(candidates, key=lambda x: df.columns.get_loc(x))[0] [cite: 29]
                [cite_start]elif potential_semester_cols: # If not found after, take the first one [cite: 30]
                    [cite_start]found_semester_column = potential_semester_cols[0] [cite: 30]
            else:
                [cite_start]found_semester_column = sorted(potential_semester_cols, key=lambda x: df.columns.get_loc(x))[0] [cite: 30]

        [cite_start]if not found_subject_column and potential_subject_cols: [cite: 30]
            [cite_start]if found_semester_column: # Subject is usually after semester [cite: 31]
                [cite_start]sem_col_idx = df.columns.get_loc(found_semester_column) [cite: 31]
                [cite_start]candidates = [col for col in potential_subject_cols if df.columns.get_loc(col) > sem_col_idx] [cite: 31]
                [cite_start]if candidates: [cite: 31]
                    [cite_start]found_subject_column = sorted(candidates, key=lambda x: df.columns.get_loc(x))[0] [cite: 31]
                [cite_start]elif potential_subject_cols: [cite: 32]
                    [cite_start]found_subject_column = potential_subject_cols[0] [cite: 32]
            else:
                [cite_start]found_subject_column = sorted(potential_subject_cols, key=lambda x: df.columns.get_loc(x))[0] [cite: 32]

        [cite_start]if not found_credit_column and potential_credit_cols: [cite: 32]
            [cite_start]if found_subject_column: # Credit is usually after subject [cite: 32, 33]
                [cite_start]subject_col_idx = df.columns.get_loc(found_subject_column) [cite: 33]
                [cite_start]candidates = [col for col in potential_credit_cols if df.columns.get_loc(col) > subject_col_idx] [cite: 33]
                [cite_start]if candidates: [cite: 33]
                    [cite_start]found_credit_column = sorted(candidates, key=lambda x: df.columns.get_loc(x))[0] [cite: 33]
                [cite_start]elif potential_credit_cols: [cite: 34]
                    [cite_start]found_credit_column = potential_credit_cols[0] [cite: 34]
            else:
                [cite_start]found_credit_column = sorted(potential_credit_cols, key=lambda x: df.columns.get_loc(x))[0] [cite: 34]

        [cite_start]if not found_gpa_column and potential_gpa_cols: [cite: 34]
            [cite_start]if found_credit_column: # GPA is usually after credit [cite: 34, 35]
                [cite_start]credit_col_idx = df.columns.get_loc(found_credit_column) [cite: 35]
                [cite_start]candidates = [col for col in potential_gpa_cols if df.columns.get_loc(col) > credit_col_idx] [cite: 35]
                [cite_start]if candidates: [cite: 35]
                    [cite_start]found_gpa_column = sorted(candidates, key=lambda x: df.columns.get_loc(x))[0] [cite: 35]
                [cite_start]elif potential_gpa_cols: [cite: 36]
                    [cite_start]found_gpa_column = potential_gpa_cols[0] [cite: 36]
            else:
                [cite_start]found_gpa_column = sorted(potential_gpa_cols, key=lambda x: df.columns.get_loc(x))[0] [cite: 36]
        
        # [cite_start]Proceed only if essential columns are found [cite: 36]
        [cite_start]if found_credit_column and found_subject_column and found_year_column and found_semester_column: # All 4 essential columns must be present [cite: 36]
            try:
                [cite_start]for row_idx, row in df.iterrows(): [cite: 37]
                    # [cite_start]Skip rows that appear to be empty or just administrative text [cite: 37]
                    [cite_start]row_content = [normalize_text(str(cell)) for cell in row] [cite: 37]
                    [cite_start]if all(cell == "" for cell in row_content) or \ [cite: 38]
                       [cite_start]any("體育室" in cell or "本表僅供查詢" in cell or "學號" in cell or "勞作" in cell for cell in row_content): [cite: 38]
                        continue

                    [cite_start]extracted_credit = 0.0 [cite: 38]
                    [cite_start]extracted_gpa = "" [cite: 39]

                    # [cite_start]Extract from credit column first, it might contain both [cite: 39]
                    [cite_start]if found_credit_column in row and pd.notna(row[found_credit_column]): [cite: 39]
                        [cite_start]extracted_credit, extracted_gpa_from_credit_col = parse_credit_and_gpa(row[found_credit_column]) [cite: 39]
                        [cite_start]if extracted_gpa_from_credit_col and not extracted_gpa: # Prioritize GPA from dedicated column if available [cite: 40]
                            [cite_start]extracted_gpa = extracted_gpa_from_credit_col [cite: 40]
                    
                    # [cite_start]Then extract/override GPA from dedicated GPA column if it exists [cite: 41]
                    [cite_start]if found_gpa_column and found_gpa_column in row and pd.notna(row[found_gpa_column]): [cite: 41]
                        [cite_start]gpa_from_gpa_col_raw = normalize_text(row[found_gpa_column]) [cite: 41]
                        [cite_start]parsed_credit_from_gpa_col, parsed_gpa_from_gpa_col = parse_credit_and_gpa(gpa_from_gpa_col_raw) [cite: 41]
                        
                        [cite_start]if parsed_gpa_from_gpa_col: # Use GPA from dedicated GPA column if found [cite: 42]
                            [cite_start]extracted_gpa = parsed_gpa_from_gpa_col.upper() [cite: 42]
                        
                        # [cite_start]Only update extracted_credit if it's currently 0 and a valid credit is found in GPA column [cite: 43]
                        [cite_start]if parsed_credit_from_gpa_col > 0 and extracted_credit == 0.0: [cite: 43]
                            [cite_start]extracted_credit = parsed_credit_from_gpa_col [cite: 43]
                    
                    # [cite_start]Final check for credit value to ensure it adheres to the max 5 credit rule [cite: 44]
                    [cite_start]if extracted_credit is None or extracted_credit > 5.0: [cite: 44]
                        [cite_start]extracted_credit = 0.0 [cite: 44]

                    [cite_start]is_failing_grade = False [cite: 45]
                    [cite_start]if extracted_gpa: [cite: 45]
                        [cite_start]gpa_clean = re.sub(r'[+\-]', '', extracted_gpa).upper() [cite: 45]
                        # [cite_start]Check for failing letter grades or numeric grades below 60 [cite: 45]
                        [cite_start]if gpa_clean in failing_grades or (gpa_clean.isdigit() and float(gpa_clean) < 60): [cite: 46]
                            [cite_start]is_failing_grade = True [cite: 46]
                        [cite_start]elif gpa_clean.replace('.', '', 1).isdigit() and float(gpa_clean) < 60: # Handle float grades if any [cite: 46, 47]
                            [cite_start]is_failing_grade = True [cite: 47]
                    
                    [cite_start]is_passed_or_exempt_grade = False [cite: 47]
                    # [cite_start]Check if the grade is explicitly "通過", "抵免", etc. in either credit or GPA column [cite: 47, 48]
                    [cite_start]if (found_gpa_column and found_gpa_column in row and pd.notna(row[found_gpa_column]) and normalize_text(row[found_gpa_column]).lower() in ["通過", "抵免", "pass", "exempt"]) or \ [cite: 48]
                       (found_credit_column in row and pd.notna(row[found_credit_column]) [cite_start]and normalize_text(row[found_credit_column]).lower() in ["通過", "抵免", "pass", "exempt"]): [cite: 48]
                        [cite_start]is_passed_or_exempt_grade = True [cite: 48]
                        
                    course_name = "" # Initialize as empty string
                    [cite_start]if found_subject_column in row and pd.notna(row[found_subject_column]): [cite: 49]
                        [cite_start]temp_name = normalize_text(row[found_subject_column]) [cite: 49]
                        # [cite_start]Only accept as subject name if it's reasonably long and contains Chinese characters, not just numbers or GPA [cite: 50]
                        # Relaxed len(temp_name) >= 1 to allow for very short course names if necessary
                        [cite_start]if len(temp_name) >= 1 and re.search(r'[\u4e00-\u9fa5]', temp_name) and \ [cite: 50]
                           [cite_start]not temp_name.isdigit() and not re.match(r'^[A-Fa-f][+\-]?$', temp_name) and \ [cite: 51]
                           [cite_start]not temp_name.lower() in ["通過", "抵免", "pass", "exempt", "未知科目"] and \ [cite: 51]
                           [cite_start]not any(kw in temp_name for kw in ["學年度", "學期", "選課代號", "科目名稱", "學分", "GPA", "本表", "備註"]): # Filter out header-like or administrative text [cite: 52]
                            course_name = temp_name
                        # [cite_start]If subject cell is empty or filtered out, try adjacent columns if they look like subject names [cite: 52]
                        else: 
                            [cite_start]current_col_idx = df.columns.get_loc(found_subject_column) [cite: 20]
                            # [cite_start]Check column to the left [cite: 20]
                            [cite_start]if current_col_idx > 0: [cite: 20]
                                [cite_start]prev_col_name = df.columns[current_col_idx - 1] [cite: 20]
                                [cite_start]if prev_col_name in row and pd.notna(row[prev_col_name]): [cite: 20]
                                    [cite_start]temp_name_prev_col = normalize_text(row[prev_col_name]) [cite: 20]
                                    [cite_start]if len(temp_name_prev_col) >= 1 and re.search(r'[\u4e00-\u9fa5]', temp_name_prev_col) and \ [cite: 20]
                                        [cite_start]not temp_name_prev_col.isdigit() and not re.match(r'^[A-Fa-f][+\-]?$', temp_name_prev_col) and \ [cite: 20]
                                        [cite_start]not any(kw in temp_name_prev_col for kw in ["學年度", "學期", "選課代號", "科目名稱", "學分", "GPA"]): [cite: 20]
                                        course_name = temp_name_prev_col
                                        
                            # [cite_start]If still empty, check column to the right [cite: 20]
                            [cite_start]if not course_name and current_col_idx < len(df.columns) - 1: [cite: 20]
                                [cite_start]next_col_name = df.columns[current_col_idx + 1] [cite: 21]
                                [cite_start]if next_col_name in row and pd.notna(row[next_col_name]): [cite: 21]
                                    [cite_start]temp_name_next_col = normalize_text(row[next_col_name]) [cite: 21]
                                    [cite_start]if len(temp_name_next_col) >= 1 and re.search(r'[\u4e00-\u9fa5]', temp_name_next_col) and \ [cite: 21]
                                        [cite_start]not temp_name_next_col.isdigit() and not re.match(r'^[A-Fa-f][+\-]?$', temp_name_next_col) and \ [cite: 21]
                                        [cite_start]not any(kw in temp_name_next_col for kw in ["學年度", "學期", "選課代號", "科目名稱", "學分", "GPA"]): [cite: 21]
                                        course_name = temp_name_next_col

                    # If it's still an empty course_name and doesn't have valid credit/GPA, skip this row
                    if not course_name and extracted_credit == 0.0 and not extracted_gpa and not is_passed_or_exempt_grade:
                        continue
                    
                    # If course_name is still empty, label it as "未知科目"
                    if not course_name:
                        course_name = "未知科目"


                    # [cite_start]Extract academic year and semester [cite: 21]
                    [cite_start]acad_year = "" [cite: 21]
                    [cite_start]semester = "" [cite: 22]
                    [cite_start]if found_year_column in row and pd.notna(row[found_year_column]): [cite: 22]
                        [cite_start]temp_year = normalize_text(row[found_year_column]) [cite: 22]
                        [cite_start]year_match = re.search(r'(\d{3,4})', temp_year) [cite: 22]
                        [cite_start]if year_match: [cite: 22]
                            [cite_start]acad_year = year_match.group(1) [cite: 22]
                    
                    [cite_start]if found_semester_column in row and pd.notna(row[found_semester_column]): [cite: 22]
                        [cite_start]temp_sem = normalize_text(row[found_semester_column]) [cite: 22]
                        [cite_start]sem_match = re.search(r'(上|下|春|夏|秋|冬|1|2|3|春季|夏季|秋季|冬季|spring|summer|fall|winter)', temp_sem, re.IGNORECASE) [cite: 22]
                        [cite_start]if sem_match: [cite: 22]
                            [cite_start]semester = sem_match.group(1) [cite: 22]

                    # [cite_start]Fallback for year/semester if not found in dedicated columns (e.g., if they are in the first few generic columns) [cite: 22]
                    [cite_start]if not acad_year and len(df.columns) > 0 and df.columns[0] in row and pd.notna(row[df.columns[0]]): [cite: 22]
                        [cite_start]temp_first_col = normalize_text(row[df.columns[0]]) [cite: 22]
                        [cite_start]year_match = re.search(r'(\d{3,4})', temp_first_col) [cite: 22]
                        [cite_start]if year_match: [cite: 22]
                            [cite_start]acad_year = year_match.group(1) [cite: 22]
                        [cite_start]if not semester: [cite: 22]
                             [cite_start]sem_match = re.search(r'(上|下|春|夏|秋|冬|1|2|3|春季|夏季|秋季|冬季|spring|summer|fall|winter)', temp_first_col, re.IGNORECASE) [cite: 22]
                             [cite_start]if sem_match: [cite: 22]
                                 [cite_start]semester = sem_match.group(1) [cite: 22]

                    [cite_start]if not semester and len(df.columns) > 1 and df.columns[1] in row and pd.notna(row[df.columns[1]]): [cite: 22]
                        [cite_start]temp_second_col = normalize_text(row[df.columns[1]]) [cite: 22]
                        [cite_start]sem_match = re.search(r'(上|下|春|夏|秋|冬|1|2|3|春季|夏季|秋季|冬季|spring|summer|fall|winter)', temp_second_col, re.IGNORECASE) [cite: 22]
                        [cite_start]if sem_match: [cite: 22]
                            [cite_start]semester = sem_match.group(1) [cite: 22]

                    [cite_start]if is_failing_grade: [cite: 22]
                        failed_courses.append({
                            [cite_start]"學年度": acad_year, [cite: 23]
                            [cite_start]"學期": semester, [cite: 23]
                            [cite_start]"科目名稱": course_name, [cite: 23] 
                            [cite_start]"學分": extracted_credit, [cite: 23] 
                            [cite_start]"GPA": extracted_gpa, [cite: 23] 
                            [cite_start]"來源表格": df_idx + 1 [cite: 23]
                        })
                    [cite_start]elif extracted_credit > 0 or is_passed_or_exempt_grade: [cite: 23]
                        [cite_start]if extracted_credit > 0: [cite: 23] 
                            [cite_start]total_credits += extracted_credit [cite: 23]
                        calculated_courses.append({
                            [cite_start]"學年度": acad_year, [cite: 23]
                            [cite_start]"學期": semester, [cite: 23]
                            [cite_start]"科目名稱": course_name, [cite: 23] 
                            [cite_start]"學分": extracted_credit, [cite: 23] 
                            [cite_start]"GPA": extracted_gpa, [cite: 23] 
                            [cite_start]"來源表格": df_idx + 1 [cite: 23]
                        })
                
            except Exception as e:
                [cite_start]st.warning(f"表格 {df_idx + 1} 的學分計算時發生錯誤: `{e}`。該表格的學分可能無法計入總數。請檢查學分和GPA欄位數據是否正確。") [cite: 23]
        else:
            [cite_start]st.info(f"頁面 {df_idx + 1} 的表格未能識別為成績單表格 (缺少必要的 學年/學期/科目名稱/學分 欄位)。") [cite: 24]
            
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
                table_settings = {
                    "vertical_strategy": "text", 
                    "horizontal_strategy": "text", 
                    "snap_tolerance": 15,  # 為了更好的手機檔案偵測，稍微增大
                    "join_tolerance": 15,  # 為了更好的手機檔案偵測，稍微增大
                    "edge_min_length": 3, 
                    "text_tolerance": 8,  # 為了更好的手機檔案偵測，稍微增大
                    "min_words_vertical": 1, 
                    "min_words_horizontal": 1, 
                }
                
                try:
                    tables = current_page.extract_tables(table_settings)

                    if not tables:
                        [cite_start]st.info(f"頁面 **{page_num + 1}** 未偵測到表格。這可能是由於 PDF 格式複雜或表格提取設定不適用。") [cite: 24]
                        continue

                    [cite_start]for table_idx, table in enumerate(tables): [cite: 24]
                        [cite_start]processed_table = [] [cite: 24]
                        [cite_start]for row in table: [cite: 24]
                            [cite_start]normalized_row = [normalize_text(cell) for cell in row] [cite: 24]
                            # [cite_start]Filter out rows that are entirely empty after normalization [cite: 24]
                            [cite_start]if any(cell.strip() != "" for cell in normalized_row): [cite: 24]
                                processed_table.append(normalized_row)
                        
                        if not processed_table:
                            [cite_start]st.info(f"頁面 {page_num + 1} 的表格 **{table_idx + 1}** 提取後為空或全為空白行。") [cite: 24]
                            continue
                        
                        df_table_to_add = None

                        # [cite_start]Try to use the first row as header [cite: 24]
                        [cite_start]if len(processed_table) > 1: [cite: 24]
                            [cite_start]potential_header_row = processed_table[0] [cite: 24]
                            # [cite_start]使用 make_unique_columns 處理潛在的重複標頭問題 [cite: 24]
                            [cite_start]temp_unique_columns = make_unique_columns(potential_header_row) [cite: 24]
                            [cite_start]temp_data_rows = processed_table[1:] [cite: 24]

                            [cite_start]num_cols_for_df = len(temp_unique_columns) [cite: 24]
                            [cite_start]cleaned_temp_data_rows = [] [cite: 24]
                            [cite_start]for row in temp_data_rows: [cite: 24]
                                [cite_start]if len(row) > num_cols_for_df: [cite: 24]
                                    [cite_start]cleaned_temp_data_rows.append(row[:num_cols_for_df]) [cite: 24]
                                [cite_start]elif len(row) < num_cols_for_df: [cite: 24] 
                                    [cite_start]cleaned_temp_data_rows.append(row + [''] * (num_cols_for_df - len(row))) [cite: 24]
                                else:
                                    cleaned_temp_data_rows.append(row)

                            if cleaned_temp_data_rows:
                                try:
                                    df_table_with_assumed_header = pd.DataFrame(cleaned_temp_data_rows, columns=temp_unique_columns)
                                    if is_grades_table(df_table_with_assumed_header):
                                        df_table_to_add = df_table_with_assumed_header
                                        st.success(f"頁面 {page_num + 1} 的表格 {table_idx + 1} 已識別為成績單表格 (帶有偵測到的標頭)。")
                                except Exception as e_df_temp:
                                    pass # Suppress warning for now, try generic columns
                        
                        # [cite_start]If failed to use first row as header, or if it's not a grades table, try treating all rows as data [cite: 24]
                        [cite_start]if df_table_to_add is None: [cite: 24]
                            [cite_start]max_cols = max(len(row) for row in processed_table) [cite: 24]
                            [cite_start]generic_columns = make_unique_columns([f"Column_{i+1}" for i in range(max_cols)]) [cite: 24]

                            [cite_start]cleaned_all_rows_data = [] [cite: 24]
                            [cite_start]for row in processed_table: [cite: 24]
                                [cite_start]if len(row) > max_cols: [cite: 24]
                                    [cite_start]cleaned_all_rows_data.append(row[:max_cols]) [cite: 24]
                                [cite_start]elif len(row) < max_cols: [cite: 24]
                                    [cite_start]cleaned_all_rows_data.append(row + [''] * (max_cols - len(row))) [cite: 24]
                                else:
                                    cleaned_all_rows_data.append(row)
                            
                            if cleaned_all_rows_data:
                                try:
                                    df_table_all_data = pd.DataFrame(cleaned_all_rows_data, columns=generic_columns)
                                    if is_grades_table(df_table_all_data):
                                        df_table_to_add = df_table_all_data
                                        st.success(f"頁面 {page_num + 1} 的表格 {table_idx + 1} 已識別為成績單表格 (所有行皆為數據)。")
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
