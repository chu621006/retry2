import streamlit as st
import pandas as pd
import io
import pdfplumber
import re # <-- 確保有這一行

# ... (其他函數保持不變，例如 parse_gpa_to_numeric, analyze_student_grades, normalize_text) ...

# --- 4. 處理分行GPA/學分問題的函數 (在提取原始表格後立即應用) ---
def parse_gpa_credit_from_combined_cell(gpa_cell_content, credit_cell_content):
    """
    Handles cases where GPA and credit are combined in one cell, or extracted incorrectly.
    Returns cleaned GPA and credit values.
    """
    original_gpa = str(gpa_cell_content).strip()
    original_credit = str(credit_cell_content).strip()

    # Normalize both inputs first to handle problematic characters
    gpa = normalize_text(original_gpa)
    credit = normalize_text(original_credit)

    # Regex to find a potential grade and a potential number (credit)
    # Allows for optional whitespace between grade and number
    # Group 1: Grade (A-F, +, -, 抵免, 通過, or empty)
    # Group 2: Numeric part (digits and dot)
    grade_credit_pattern = re.compile(r'^\s*([A-Z\+\-抵免通過]*)\s*([0-9\.]*)\s*$')

    parsed_gpa = gpa
    parsed_credit = credit

    # Try to parse from GPA cell if credit cell is empty or looks like a grade
    if not credit or (parse_gpa_to_numeric(credit) != 0.0 and not credit.replace('.', '').isdigit()):
        match = grade_credit_pattern.match(gpa)
        if match:
            grade_part = match.group(1).strip()
            num_part = match.group(2).strip()

            # If a grade part is found and it's valid, use it for GPA
            if grade_part and (parse_gpa_to_numeric(grade_part) != 0.0 or grade_part in ['抵免', '通過']):
                parsed_gpa = grade_part
            # If a numeric part is found and it's valid, use it for credit
            if num_part and num_part.replace('.', '').isdigit():
                parsed_credit = num_part
            # If GPA cell contained "Grade Number", and credit cell was truly empty
            elif not credit and parsed_gpa != gpa and parsed_credit != credit:
                 # This means we successfully split 'gpa' cell into grade and credit
                 pass
            # Handle cases where original gpa was just "3" (a credit) and original credit was "A" (a grade) - swap them
            elif gpa.replace('.', '').isdigit() and (parse_gpa_to_numeric(credit) != 0.0 and not credit.replace('.', '').isdigit()):
                parsed_gpa = credit
                parsed_credit = gpa

    # Try to parse from Credit cell if GPA cell is empty or looks like a credit number
    if not gpa or (gpa.replace('.', '').isdigit() and parse_gpa_to_numeric(gpa) == 0.0): # gpa looks like a credit number
        match = grade_credit_pattern.match(credit)
        if match:
            grade_part = match.group(1).strip()
            num_part = match.group(2).strip()

            if grade_part and (parse_gpa_to_numeric(grade_part) != 0.0 or grade_part in ['抵免', '通過']):
                parsed_gpa = grade_part
            if num_part and num_part.replace('.', '').isdigit():
                parsed_credit = num_part
            # Handle cases where original credit was just "A" (a grade) and original gpa was "3" (a credit) - swap them
            elif credit.replace('.', '').isdigit() and (parse_gpa_to_numeric(gpa) != 0.0 and not gpa.replace('.', '').isdigit()):
                parsed_gpa = gpa
                parsed_credit = credit

    # Final check for common scenarios if one is clearly a grade and the other a number, and they were swapped
    # E.g., if gpa is "3.0" and credit is "A", swap them
    if parsed_gpa and parsed_credit:
        is_gpa_like_grade = (parse_gpa_to_numeric(parsed_gpa) != 0.0 or parsed_gpa in ['抵免', '通過']) and not parsed_gpa.replace('.', '').isdigit()
        is_credit_like_number = parsed_credit.replace('.', '').isdigit()

        if not is_gpa_like_grade and is_credit_like_number: # GPA looks like a number, Credit looks like a number
            # This is ambiguous, keep original assignment unless a swap is obvious
            pass
        elif is_gpa_like_grade and not is_credit_like_number: # GPA looks like a grade, Credit looks like a grade
            # This means both are grades, which is probably wrong, return as is and let downstream handle
            pass
        elif not is_gpa_like_grade and not is_credit_like_number: # Both not grade and not number, keep as is
            pass
        elif is_gpa_like_grade and is_credit_like_number: # Correct scenario, grade in GPA, number in credit
            pass
        else: # Unlikely, but covers other combinations
            pass
    
    # One last swap check: If one cell got "抵免" or "通過" and the other got a number, assign them correctly
    if parsed_gpa in ['抵免', '通過'] and parsed_credit.replace('.', '').isdigit():
        pass # Correctly assigned
    elif parsed_credit in ['抵免', '通過'] and parsed_gpa.replace('.', '').isdigit():
        temp_gpa = parsed_credit
        temp_credit = parsed_gpa
        parsed_gpa = temp_gpa
        parsed_credit = temp_credit

    return parsed_gpa, parsed_credit

# --- Streamlit 應用程式主體 ---
def main():
    st.title("總學分查詢系統 🎓")
    st.write("請上傳您的成績總表 PDF 檔案，系統將會為您查詢目前總學分與距離畢業所需的學分。")
    st.info("💡 確保您的成績單 PDF 是清晰的表格格式，以獲得最佳解析效果。")

    uploaded_file = st.file_uploader("上傳成績總表 PDF 檔案", type=["pdf"])

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
                        "snap_tolerance": 2, # 微調：從 3 調整為 2
                        "text_tolerance": 2, # 微調：從 3 調整為 2
                        "join_tolerance": 2, # 微調：從 3 調整為 2
                        "edge_min_length": 3,
                        "min_words_horizontal": 1,
                        "min_words_vertical": 1
                    }
                    
                    tables = cropped_page.extract_tables(table_settings)
                    
                    if not tables:
                        continue

                    for table_idx, table in enumerate(tables):
                        if not table or len(table) < 1:
                            continue

                        filtered_table = []
                        for row in table:
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
                            if len(filtered_table[0]) > 0 and filtered_table[0][0].isdigit() and len(filtered_table[0][0]) == 3:
                                header = expected_header_keywords
                                header_row_start_idx = -1
                                header_row_found = True
                            else:
                                continue

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
                        current_row_data_temp = [""] * len(expected_header_keywords)

                        data_rows_to_process = filtered_table[header_row_start_idx + 1:] if header_row_start_idx != -1 else filtered_table[:]

                        for row_num_in_table, row_cells in enumerate(data_rows_to_process):
                            if not any(str(cell).strip() for cell in row_cells):
                                continue

                            max_idx = max(col_to_index.values()) if col_to_index else 0
                            row_cells_padded = row_cells + [''] * (max_idx + 1 - len(row_cells))

                            學年度_val = row_cells_padded[學年度_idx] if 學年度_idx is not None and 學年度_idx < len(row_cells_padded) else ''
                            選課代號_val = row_cells_padded[選課代號_idx] if 選課代號_idx is not None and 選課代號_idx < len(row_cells_padded) else ''
                            科目名稱_val = row_cells_padded[科目名稱_idx] if 科目名稱_idx is not None and 科目名稱_idx < len(row_cells_padded) else ''
                            學分_val = row_cells_padded[學分_idx] if 學分_idx is not None and 學分_idx < len(row_cells_padded) else ''
                            GPA_val = row_cells_padded[GPA_idx] if GPA_idx is not None and GPA_idx < len(row_cells_padded) else ''

                            is_new_grade_row = False
                            if 學年度_val.isdigit() and len(學年度_val) == 3 and \
                               (選課代號_val.strip() != '' or 科目名稱_val.strip() != ''):
                                is_new_grade_row = True
                            
                            if is_new_grade_row:
                                if current_row_data_temp and any(x is not None and str(x).strip() for x in current_row_data_temp):
                                    processed_rows.append(current_row_data_temp[:])
                                
                                current_row_data_temp = [""] * len(expected_header_keywords)

                                if 學年度_idx is not None: current_row_data_temp[expected_header_keywords.index("學年度")] = 學年度_val
                                if 學期_idx is not None: current_row_data_temp[expected_header_keywords.index("學期")] = (row_cells_padded[學期_idx] if 學期_idx is not None and 學期_idx < len(row_cells_padded) else '')
                                if 選課代號_idx is not None: current_row_data_temp[expected_header_keywords.index("選課代號")] = 選課代號_val
                                if 科目名稱_idx is not None: current_row_data_temp[expected_header_keywords.index("科目名稱")] = 科目名稱_val
                                
                                # Apply parsing for GPA and Credit immediately
                                current_gpa, current_credit = parse_gpa_credit_from_combined_cell(GPA_val, 學分_val)
                                current_row_data_temp[expected_header_keywords.index("GPA")] = current_gpa
                                current_row_data_temp[expected_header_keywords.index("學分")] = current_credit

                            elif current_row_data_temp:
                                is_continuation_candidate = (學年度_val.strip() == '' and 選課代號_val.strip() == '')

                                if is_continuation_candidate and 科目名稱_val.strip() != '':
                                    current_subject_name_index = expected_header_keywords.index("科目名稱")
                                    current_subject_name = current_row_data_temp[current_subject_name_index]
                                    if current_subject_name.strip() == "":
                                        current_row_data_temp[current_subject_name_index] = 科目名稱_val
                                    else:
                                        current_row_data_temp[current_subject_name_index] += " " + 科目名稱_val
                                
                                # For continuation rows, try to update GPA/Credit if they are found in this row
                                if is_continuation_candidate and (學分_val.strip() != '' or GPA_val.strip() != ''):
                                    merged_gpa, merged_credit = parse_gpa_credit_from_combined_cell(GPA_val, 學分_val)
                                    
                                    credit_index = expected_header_keywords.index("學分")
                                    gpa_index = expected_header_keywords.index("GPA")

                                    # Only update if current temp is empty or new value is more complete
                                    if current_row_data_temp[credit_index].strip() == "" and merged_credit.strip() != "":
                                        current_row_data_temp[credit_index] = merged_credit
                                    if current_row_data_temp[gpa_index].strip() == "" and merged_gpa.strip() != "":
                                        current_row_data_temp[gpa_index] = merged_gpa


                        if current_row_data_temp and any(x is not None and str(x).strip() for x in current_row_data_temp):
                            processed_rows.append(current_row_data_temp[:])
                        
                        if processed_rows:
                            df_table = pd.DataFrame(processed_rows, columns=expected_header_keywords)
                            
                            for col in df_table.columns:
                                df_table[col] = df_table[col].astype(str).str.strip().replace('None', '').replace('nan', '')

                            all_grades_data.append(df_table)
                        else:
                            pass

            if not all_grades_data:
                st.warning("未能從 PDF 中提取有效的成績數據。請檢查 PDF 格式或調整表格提取設定。")
                full_grades_df = pd.DataFrame(columns=expected_header_keywords)
            else:
                full_grades_df = pd.concat(all_grades_data, ignore_index=True)

                full_grades_df.dropna(how='all', inplace=True)
                
                if '學年度' in full_grades_df.columns and '選課代號' in full_grades_df.columns:
                    full_grades_df = full_grades_df[
                        full_grades_df['學年度'].astype(str).str.match(r'^\d{3}$') &
                        (full_grades_df['選課代號'].astype(str).str.strip() != '')
                    ]

                if '科目名稱' in full_grades_df.columns:
                    full_grades_df = full_grades_df[~full_grades_df['科目名稱'].astype(str).str.contains('勞作成績', na=False)]
                
                if 'GPA' in full_grades_df.columns:
                    full_grades_df['GPA'] = full_grades_df['GPA'].astype(str).str.strip()
                
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
            st.exception(e)

if __name__ == "__main__":
    main()
