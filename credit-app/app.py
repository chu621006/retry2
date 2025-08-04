import streamlit as st
import pandas as pd
import io
import pdfplumber
import re

# --- 1. 定義輔助函數 ---

def normalize_text(text):
    """
    標準化文本：移除換行符、全形空格，並修剪空白。
    """
    if text is None:
        return ""
    text = str(text) # 確保輸入是字串
    # 移除換行符、回車符，並將全形空格轉換為半形空格，然後修剪前後空白
    text = text.replace('\n', ' ').replace('\r', '').replace('\u3000', ' ').strip()
    # 針對中文標點符號的替換，這部分您之前可能有定義，這裡可以保留或添加
    text = text.replace('，', ',').replace('。', '.').replace('：', ':').replace('；', ';')
    text = text.replace('　', ' ') # 再次處理全形空格
    return text

def parse_gpa_to_numeric(gpa_str):
    """
    將 GPA 字串轉換為數值，處理特殊值如 '抵免' 和 '通過'。
    """
    gpa_str = normalize_text(gpa_str)
    gpa_mapping = {
        'A+': 4.3, 'A': 4.0, 'A-': 3.7,
        'B+': 3.3, 'B': 3.0, 'B-': 2.7,
        'C+': 2.3, 'C': 2.0, 'C-': 1.7,
        'D+': 1.3, 'D': 1.0, 'D-': 0.7,
        'E': 0.0, 'F': 0.0, 'X': 0.0,
        '抵免': 0.0, '通過': 0.0, '': 0.0, 'None': 0.0
    }
    return gpa_mapping.get(gpa_str, 0.0)

def parse_gpa_credit_from_combined_cell(gpa_cell_content, credit_cell_content):
    """
    Handles cases where GPA and credit are combined in one cell, or extracted incorrectly.
    Returns cleaned GPA and credit values.
    """
    original_gpa = str(gpa_cell_content).strip()
    original_credit = str(credit_cell_content).strip()

    gpa = normalize_text(original_gpa)
    credit = normalize_text(original_credit)

    # Regex to find a potential grade and a potential number (credit)
    # Allows for optional whitespace between grade and number
    # Group 1: Grade (A-Z, +, -, 抵免, 通過, or empty)
    # Group 2: Numeric part (digits and optional dot)
    grade_credit_pattern = re.compile(r'^\s*([A-Z\+\-抵免通過]*)\s*([0-9\.]*)\s*$')

    parsed_gpa = gpa
    parsed_credit = credit

    # Scenario 1: Credit cell is empty or clearly a grade, try to parse from GPA cell
    if not credit or (parse_gpa_to_numeric(credit) != 0.0 and not credit.replace('.', '').isdigit()):
        match = grade_credit_pattern.match(gpa)
        if match:
            grade_part = match.group(1).strip()
            num_part = match.group(2).strip()

            if grade_part and (parse_gpa_to_numeric(grade_part) != 0.0 or grade_part in ['抵免', '通過']):
                parsed_gpa = grade_part
            if num_part and num_part.replace('.', '').isdigit():
                parsed_credit = num_part
            # If GPA cell contained "Grade Number" and credit cell was truly empty
            elif not credit and parsed_gpa != gpa and parsed_credit != credit:
                pass
            # Specific swap: original gpa was a number, original credit was a grade
            elif gpa.replace('.', '').isdigit() and (parse_gpa_to_numeric(credit) != 0.0 and not credit.replace('.', '').isdigit()):
                parsed_gpa = credit # credit was the grade
                parsed_credit = gpa # gpa was the number

    # Scenario 2: GPA cell is empty or looks like a credit number, try to parse from Credit cell
    if not gpa or (gpa.replace('.', '').isdigit() and parse_gpa_to_numeric(gpa) == 0.0):
        match = grade_credit_pattern.match(credit)
        if match:
            grade_part = match.group(1).strip()
            num_part = match.group(2).strip()

            if grade_part and (parse_gpa_to_numeric(grade_part) != 0.0 or grade_part in ['抵免', '通過']):
                parsed_gpa = grade_part
            if num_part and num_part.replace('.', '').isdigit():
                parsed_credit = num_part
            # Specific swap: original credit was a number, original gpa was a grade
            elif credit.replace('.', '').isdigit() and (parse_gpa_to_numeric(gpa) != 0.0 and not gpa.replace('.', '').isdigit()):
                parsed_gpa = gpa # gpa was the grade
                parsed_credit = credit # credit was the number

    # Final consistency check if both have values
    if parsed_gpa and parsed_credit:
        is_gpa_like_grade = (parse_gpa_to_numeric(parsed_gpa) != 0.0 or parsed_gpa in ['抵免', '通過']) and not parsed_gpa.replace('.', '').isdigit()
        is_credit_like_number = parsed_credit.replace('.', '').isdigit()

        if is_gpa_like_grade and is_credit_like_number:
            # Correctly assigned, do nothing
            pass
        elif is_credit_like_number and (not is_gpa_like_grade or parsed_gpa == ''): # Credit is numeric, GPA is not a grade or empty
            # If the original GPA cell content actually looked like a grade, but got misassigned
            if original_gpa and (parse_gpa_to_numeric(original_gpa) != 0.0 or original_gpa in ['抵免', '通過']):
                parsed_gpa = normalize_text(original_gpa)
                # Keep parsed_credit as it's numeric
        elif is_gpa_like_grade and (not is_credit_like_number or parsed_credit == ''): # GPA is grade, Credit is not numeric or empty
            # If the original Credit cell content actually looked like a number
            if original_credit and original_credit.replace('.', '').isdigit():
                parsed_credit = normalize_text(original_credit)
                # Keep parsed_gpa as it's a grade
    
    # Handle "抵免" or "通過" in credit cell, which should be in GPA
    if parsed_credit in ['抵免', '通過'] and parsed_gpa.replace('.', '').isdigit():
        temp_gpa = parsed_credit
        temp_credit = parsed_gpa
        parsed_gpa = temp_gpa
        parsed_credit = temp_credit

    return parsed_gpa, parsed_credit


def analyze_student_grades(df):
    """
    分析學生的成績 DataFrame，計算總學分、所需學分和通過的課程。
    """
    if df.empty:
        return 0, 128, pd.DataFrame(columns=['學年度', '學期', '科目名稱', '學分', 'GPA'])

    # 確保 GPA 和 學分 欄位是正確的數據類型
    df['GPA_Numeric'] = df['GPA'].apply(parse_gpa_to_numeric)
    # 將 '學分' 轉換為數值，無法轉換的設為 NaN，然後填充為 0
    df['學分'] = pd.to_numeric(df['學分'], errors='coerce').fillna(0)

    # 假設通過的標準是 GPA > 0，且不是 '抵免' 或 '通過' 但學分不為0
    # 或者 GPA 是 '抵免' 或 '通過'
    passed_courses_df = df[
        ((df['GPA_Numeric'] > 0) | (df['GPA'].isin(['抵免', '通過']))) &
        (df['學分'] > 0) # 確保學分大於 0
    ].copy() # 使用 .copy() 避免 SettingWithCopyWarning

    total_credits = passed_courses_df['學分'].sum()
    required_credits = 128
    remaining_credits = max(0, required_credits - total_credits)

    return total_credits, remaining_credits, passed_courses_df

# --- Streamlit 應用程式主體 ---
def main():
    st.title("總學分查詢系統 🎓")
    st.write("請上傳您的成績總表 PDF 檔案，系統將會為您查詢目前總學分與距離畢業所需的學分。")
    st.info("💡 確保您的成績單 PDF 是清晰的表格格式，以獲得最佳解析效果。")

    uploaded_file = st.file_uploader("上傳成績總表 PDF 檔案", type=["pdf"])

    # 確保 all_grades_data 和 full_grades_df 在 main 函數開始時被初始化
    all_grades_data = [] 
    full_grades_df = pd.DataFrame() 

    if uploaded_file is not None:
        st.success("檔案上傳成功！正在分析中...")

        try:
            expected_header_keywords = ["學年度", "學期", "選課代號", "科目名稱", "學分", "GPA"]
            
            with pdfplumber.open(io.BytesIO(uploaded_file.getvalue())) as pdf:
                total_pages = len(pdf.pages)

                for page_num, page in enumerate(pdf.pages):
                    top_y_crop = 0
                    bottom_y_crop = page.height

                    # 針對特定檔案名調整裁剪高度
                    if "謝云瑄成績總表.pdf" in uploaded_file.name:
                        top_y_crop = 170 if page_num == 0 else 50
                        bottom_y_crop = page.height - 30
                    elif "邱旭廷成績總表.pdf" in uploaded_file.name:
                        top_y_crop = 250 if page_num == 0 else 50
                        bottom_y_crop = page.height - 30
                    else:
                        top_y_crop = 100 if page_num == 0 else 50
                        bottom_y_crop = page.height - 30

                    cropped_page = page.crop((0, top_y_crop, page.width, bottom_y_crop))
                    
                    # 嘗試更細緻的 table_settings
                    table_settings = {
                        "vertical_strategy": "lines",
                        "horizontal_strategy": "lines",
                        "snap_tolerance": 2, 
                        "text_tolerance": 2, 
                        "join_tolerance": 2, 
                        "edge_min_length": 3,
                        "min_words_horizontal": 1,
                        "min_words_vertical": 1
                        # "keep_blank_chars": True # 移除此行，可能導致 TypeError
                    }
                    
                    tables = cropped_page.extract_tables(table_settings)
                    
                    if not tables:
                        continue

                    for table_idx, table in enumerate(tables):
                        if not table or len(table) < 1:
                            continue

                        filtered_table = []
                        for row in table:
                            # 確保 cell 是字串，並呼叫 normalize_text
                            normalized_row = [normalize_text(cell) for cell in row] 
                            if any(cell.strip() for cell in normalized_row):
                                filtered_table.append(normalized_row)
                        
                        if not filtered_table:
                            continue
                        
                        header_row_found = False
                        header = []
                        header_row_start_idx = -1

                        potential_header_search_range = min(len(filtered_table), 5)
                        for h_idx in range(potential_header_search_range):
                            h_row_cells = [cell.strip() for cell in filtered_table[h_idx]]
                            
                            header_match_criteria = [
                                any("學年" in cell for cell in h_row_cells),
                                any("科目名稱" in cell for cell in h_row_cells),
                                any("學分" in cell for cell in h_row_cells),
                                any("GPA" in cell for cell in h_row_cells)
                            ]

                            if all(header_match_criteria):
                                header = h_row_cells
                                header_row_found = True
                                header_row_start_idx = h_idx
                                break
                        
                        if not header_row_found:
                            # 針對某些 PDF 可能沒有明確表頭，但第一行是數據的情況
                            # 例如，如果第一行看起來像學年度（三位數字）
                            if len(filtered_table[0]) > 0 and filtered_table[0][0].isdigit() and len(filtered_table[0][0]) == 3:
                                header = expected_header_keywords
                                header_row_start_idx = -1 # 表示沒有找到明確的表頭行，從第一行開始就是數據
                                header_row_found = True
                            else:
                                continue # 如果沒有找到表頭，且第一行也不像數據，則跳過此表格

                        col_to_index = {}
                        for i, h_text in enumerate(header):
                            if "學年" in h_text: col_to_index["學年度"] = i
                            elif "學期" in h_text: col_to_index["學期"] = i
                            elif "選課代號" in h_text: col_to_index["選課代號"] = i
                            elif "科目名稱" in h_text: col_to_index["科目名稱"] = i
                            elif "學分" in h_text: col_to_index["學分"] = i
                            elif "GPA" in h_text: col_to_index["GPA"] = i

                        critical_cols = ["學年度", "科目名稱", "學分", "GPA"]
                        if not all(col in col_to_index for col in critical_cols):
                            st.warning(f"頁面 {page_num + 1} 的表格 {table_idx + 1} 缺少關鍵列。跳過此表格。")
                            continue

                        學年度_idx = col_to_index.get("學年度")
                        學期_idx = col_to_index.get("學期")
                        選課代號_idx = col_to_index.get("選課代號")
                        科目名稱_idx = col_to_index.get("科目名稱")
                        學分_idx = col_to_index.get("學分")
                        GPA_idx = col_to_index.get("GPA")

                        processed_rows = []
                        # 初始化 current_row_data_temp，確保所有列都有預設值
                        current_row_data_temp = [""] * len(expected_header_keywords)

                        data_rows_to_process = filtered_table[header_row_start_idx + 1:] if header_row_start_idx != -1 else filtered_table[:]

                        for row_num_in_table, row_cells in enumerate(data_rows_to_process):
                            if not any(str(cell).strip() for cell in row_cells): # 跳過空行
                                continue

                            # 確保 row_cells_padded 足夠長
                            max_idx_needed = max(學年度_idx, 學期_idx, 選課代號_idx, 科目名稱_idx, 學分_idx, GPA_idx) if col_to_index else 0
                            row_cells_padded = row_cells + [''] * (max_idx_needed + 1 - len(row_cells))

                            學年度_val = row_cells_padded[學年度_idx] if 學年度_idx is not None and 學年度_idx < len(row_cells_padded) else ''
                            選課代號_val = row_cells_padded[選課代號_idx] if 選課代號_idx is not None and 選課代號_idx < len(row_cells_padded) else ''
                            科目名稱_val = row_cells_padded[科目名稱_idx] if 科目名稱_idx is not None and 科目名稱_idx < len(row_cells_padded) else ''
                            學分_val = row_cells_padded[學分_idx] if 學分_idx is not None and 學分_idx < len(row_cells_padded) else ''
                            GPA_val = row_cells_padded[GPA_idx] if GPA_idx is not None and GPA_idx < len(row_cells_padded) else ''

                            is_new_grade_row = False
                            # 判斷是否為新的課程行：學年度是三位數字，且選課代號或科目名稱不為空
                            if 學年度_val.isdigit() and len(學年度_val) == 3 and \
                               (選課代號_val.strip() != '' or 科目名稱_val.strip() != ''):
                                is_new_grade_row = True
                            
                            if is_new_grade_row:
                                # 如果已經有正在處理的行數據，先將其添加到 processed_rows
                                if current_row_data_temp and any(x is not None and str(x).strip() for x in current_row_data_temp):
                                    processed_rows.append(current_row_data_temp[:])
                                
                                # 開始處理新的行
                                current_row_data_temp = [""] * len(expected_header_keywords)

                                if 學年度_idx is not None: current_row_data_temp[expected_header_keywords.index("學年度")] = 學年度_val
                                if 學期_idx is not None: current_row_data_temp[expected_header_keywords.index("學期")] = (row_cells_padded[學期_idx] if 學期_idx is not None and 學期_idx < len(row_cells_padded) else '')
                                if 選課代號_idx is not None: current_row_data_temp[expected_header_keywords.index("選課代號")] = 選課代號_val
                                if 科目名稱_idx is not None: current_row_data_temp[expected_header_keywords.index("科目名稱")] = 科目名稱_val
                                
                                # 對 GPA 和 學分 進行解析
                                current_gpa, current_credit = parse_gpa_credit_from_combined_cell(GPA_val, 學分_val)
                                current_row_data_temp[expected_header_keywords.index("GPA")] = current_gpa
                                current_row_data_temp[expected_header_keywords.index("學分")] = current_credit

                            elif current_row_data_temp: # 如果不是新行，則可能是前一行的延續
                                is_continuation_candidate = (學年度_val.strip() == '' and 選課代號_val.strip() == '')

                                if is_continuation_candidate and 科目名稱_val.strip() != '':
                                    current_subject_name_index = expected_header_keywords.index("科目名稱")
                                    current_subject_name = current_row_data_temp[current_subject_name_index]
                                    if current_subject_name.strip() == "": # 如果科目名稱是空的，直接填充
                                        current_row_data_temp[current_subject_name_index] = 科目名稱_val
                                    else: # 如果科目名稱不為空，則拼接
                                        current_row_data_temp[current_subject_name_index] += " " + 科目名稱_val
                                
                                # 對於延續行，如果學分或 GPA 被找到，則更新
                                if is_continuation_candidate and (學分_val.strip() != '' or GPA_val.strip() != ''):
                                    merged_gpa, merged_credit = parse_gpa_credit_from_combined_cell(GPA_val, 學分_val)
                                    
                                    credit_index = expected_header_keywords.index("學分")
                                    gpa_index = expected_header_keywords.index("GPA")

                                    if current_row_data_temp[credit_index].strip() == "" and merged_credit.strip() != "":
                                        current_row_data_temp[credit_index] = merged_credit
                                    if current_row_data_temp[gpa_index].strip() == "" and merged_gpa.strip() != "":
                                        current_row_data_temp[gpa_index] = merged_gpa

                        # 將最後一行的數據添加到 processed_rows
                        if current_row_data_temp and any(x is not None and str(x).strip() for x in current_row_data_temp):
                            processed_rows.append(current_row_data_temp[:])
                        
                        if processed_rows:
                            df_table = pd.DataFrame(processed_rows, columns=expected_header_keywords)
                            
                            # 對 DataFrame 中的所有列進行最終的字串清理
                            for col in df_table.columns:
                                df_table[col] = df_table[col].astype(str).str.strip().replace('None', '').replace('nan', '')

                            all_grades_data.append(df_table)
                        else:
                            pass # 沒有處理好的行，跳過此表格

            if not all_grades_data:
                st.warning("未能從 PDF 中提取有效的成績數據。請檢查 PDF 格式或調整表格提取設定。")
                full_grades_df = pd.DataFrame(columns=expected_header_keywords)
            else:
                full_grades_df = pd.concat(all_grades_data, ignore_index=True)

                # 進一步清理 DataFrame
                full_grades_df.dropna(how='all', inplace=True)
                
                # 過濾掉不符合學年度和選課代號模式的行
                if '學年度' in full_grades_df.columns and '選課代號' in full_grades_df.columns:
                    full_grades_df = full_grades_df[
                        full_grades_df['學年度'].astype(str).str.match(r'^\d{3}$') &
                        (full_grades_df['選課代號'].astype(str).str.strip() != '')
                    ]

                # 過濾掉「勞作成績」
                if '科目名稱' in full_grades_df.columns:
                    full_grades_df = full_grades_df[~full_grades_df['科目名稱'].astype(str).str.contains('勞作成績', na=False)]
                
                # 確保 GPA 欄位是字串並修剪
                if 'GPA' in full_grades_df.columns:
                    full_grades_df['GPA'] = full_grades_df['GPA'].astype(str).str.strip()
                
                # 將學分轉換為數值，非數字的設為0
                if '學分' in full_grades_df.columns:
                    full_grades_df['學分'] = pd.to_numeric(full_grades_df['學分'], errors='coerce').fillna(0)


            if not full_grades_df.empty:
                total_credits, remaining_credits, passed_courses_df = analyze_student_grades(full_grades_df)

                st.subheader("查詢結果 ✅")
                st.metric("目前總學分", total_credits)
                st.metric("距離畢業所需學分 (共128學分)", remaining_credits)

                st.subheader("通過的課程列表 📖")
                st.dataframe(passed_courses_df[['學年度', '學期', '科目名稱', '學分', 'GPA']])

                with st.expander("查看原始提取的數據 (用於除錯)"):
                    st.dataframe(full_grades_df)
            else:
                st.warning("未能從 PDF 中提取有效的成績數據。請檢查 PDF 格式。")

        except Exception as e:
            st.error(f"處理 PDF 檔案時發生錯誤：{e}")
            st.info("請確認您的 PDF 格式是否為清晰的表格。若問題持續，可能是 PDF 結構較為複雜，需要調整 `pdfplumber` 的表格提取設定。")
            st.exception(e) # 顯示完整的錯誤追蹤，方便除錯

if __name__ == "__main__":
    main()
