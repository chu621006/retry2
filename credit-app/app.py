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
    
    failing_grades = ["D", "D-", "E", "F", "X", "不通過", "未通過", "不及格"] # 增加 '不及格'

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
                # 兼容 "通過", "抵免", "Pass", "Exempt" 這種情況
                if item_str.lower() in ["通過", "抵免", "pass", "exempt"]: 
                    numeric_like_count += 1
                else:
                    credit_val, _ = parse_credit_and_gpa(item_str)
                    if 0.0 < credit_val <= 10.0: # 學分大於0且在合理範圍內
                        numeric_like_count += 1
            if total_sample_count > 0 and numeric_like_count / total_sample_count >= 0.6: 
                potential_credit_columns.append(col_name)

            # 判斷潛在科目名稱欄位 (更智能的判斷)
            subject_like_count = 0
            for item_str in sample_data:
                # 判斷是否看起來像科目名稱: 包含中文字符，長度通常較長 (>4個字), 且不全是數字或單個字母成績
                if re.search(r'[\u4e00-\u9fa5]', item_str) and len(item_str) > 4 and not item_str.isdigit() and not re.match(r'^[A-Fa-f][+\-]?$', item_str) and not item_str.lower() in ["通過", "抵免", "pass", "exempt"]: 
                    subject_like_count += 1
            if total_sample_count > 0 and subject_like_count / total_sample_count >= 0.7: 
                potential_subject_columns.append(col_name)

            # 判斷潛在 GPA 欄位
            gpa_like_count = 0
            for item_str in sample_data:
                # 檢查是否是標準的 GPA 字母等級 (A+, B-, C, D, E, F) 或數字分數
                if re.match(r'^[A-Fa-f][+\-]?' , item_str) or (item_str.isdigit() and len(item_str) <=3): # 考慮分數
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


        if found_credit_column:
            try:
                for row_idx, row in df.iterrows():
                    # 嘗試從學分或 GPA 欄位獲取學分和 GPA
                    extracted_credit = 0.0
                    extracted_gpa = ""

                    if found_credit_column:
                        extracted_credit, extracted_gpa_from_credit_col = parse_credit_and_gpa(row[found_credit_column])
                        if extracted_gpa_from_credit_col: # 如果從學分欄位同時解析出GPA，則優先使用
                            extracted_gpa = extracted_gpa_from_credit_col
                    
                    if found_gpa_column and not extracted_gpa: # 如果 GPA 欄位存在且尚未從學分欄位獲取到 GPA
                        gpa_from_gpa_col = normalize_text(row[found_gpa_column])
                        if gpa_from_gpa_col:
                            extracted_gpa = gpa_from_gpa_col.upper()
                    
                    # 確保學分值不為 None
                    if extracted_credit is None:
                        extracted_credit = 0.0

                    is_failing_grade = False
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
                    
                    # 處理「通過」和「抵免」情況
                    # 即使有學分值，如果 GPA 欄位明確為「通過」或「抵免」，則不計入總學分
                    if (found_gpa_column and normalize_text(row[found_gpa_column]).lower() in ["通過", "抵免", "pass", "exempt"]) or \
                       (found_credit_column and normalize_text(row[found_credit_column]).lower() in ["通過", "抵免", "pass", "exempt"]):
                        extracted_credit = 0.0 # 強制設為0學分，不計入總學分

                    course_name = "未知科目" 
                    if found_subject_column and found_subject_column in row:
