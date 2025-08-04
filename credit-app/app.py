import streamlit as st
import pandas as pd
import io
import pdfplumber

# --- 1. GPA 轉換函數 ---
def parse_gpa_to_numeric(gpa_str):
    """
    Converts GPA string to a numeric value for comparison.
    This mapping can be adjusted based on specific grading scales.
    For this example, we define C- and above as passing.
    """
    gpa_map = {
        'A+': 4.3, 'A': 4.0, 'A-': 3.7,
        'B+': 3.3, 'B': 3.0, 'B-': 2.7,
        'C+': 2.3, 'C': 2.0, 'C-': 1.7,
        'D+': 1.3, 'D': 1.0, 'D-': 0.7,
        'E': 0.0, 'F': 0.0,
        '抵免': 999.0, # 抵免也算通過
        '通過': 999.0  # 通過也算通過
    }
    return gpa_map.get(str(gpa_str).strip(), 0.0)

# --- 2. 成績分析函數 ---
def analyze_student_grades(df):
    """
    Analyzes a DataFrame of student grades to calculate total earned credits
    and remaining credits for graduation.
    """
    GRADUATION_REQUIREMENT = 128

    df['學分'] = pd.to_numeric(df['學分'], errors='coerce').fillna(0)
    df['GPA_Numeric'] = df['GPA'].apply(parse_gpa_to_numeric)
    df['是否通過'] = df['GPA_Numeric'].apply(lambda x: x >= 1.7)
    passed_courses_df = df[df['是否通過'] & (df['學分'] > 0)].copy()

    total_earned_credits = passed_courses_df['學分'].sum()
    remaining_credits_to_graduate = max(0, GRADUATION_REQUIREMENT - total_earned_credits)

    return total_earned_credits, remaining_credits_to_graduate, passed_courses_df

# --- Streamlit 應用程式主體 ---
def main():
    st.title("總學分查詢系統 🎓")
    st.write("請上傳您的成績總表 PDF 檔案，系統將會為您查詢目前總學分與距離畢業所需的學分。")
    st.info("💡 確保您的成績單 PDF 是清晰的表格格式，以獲得最佳解析效果。")

    uploaded_file = st.file_uploader("上傳成績總表 PDF 檔案", type=["pdf"])

    if uploaded_file is not None:
        st.success("檔案上傳成功！正在分析中...")

        try:
            all_grades_data = []
            expected_columns_order = ["學年度", "學期", "選課代號", "科目名稱", "學分", "GPA"]
            
            st.subheader("除錯資訊 (開發者專用) 🕵️")
            debug_info_placeholder = st.empty()
            debug_messages = []

            with pdfplumber.open(io.BytesIO(uploaded_file.getvalue())) as pdf:
                total_pages = len(pdf.pages)

                for page_num, page in enumerate(pdf.pages):
                    debug_messages.append(f"--- 正在處理頁面 {page_num + 1}/{total_pages} ---")

                    top_y_crop = 60 
                    bottom_y_crop = page.height 

                    cropped_page = page.crop((0, top_y_crop, page.width, bottom_y_crop)) 
                    
                    table_settings = {
                        "horizontal_strategy": "lines", 
                        "snap_tolerance": 5, 
                        "text_tolerance": 3, 
                        "join_tolerance": 3,
                        "min_words_horizontal": 1, 
                        "min_words_vertical": 1 
                    }
                    
                    tables = cropped_page.extract_tables(table_settings)
                    
                    debug_messages.append(f"頁面 {page_num + 1} 提取到 {len(tables)} 個表格。")
                    
                    if not tables:
                        debug_messages.append(f"頁面 {page_num + 1} 未提取到任何表格。")
                        continue

                    for table_idx, table in enumerate(tables):
                        debug_messages.append(f"--- 處理頁面 {page_num + 1} 的表格 {table_idx + 1} ---")
                        debug_messages.append(f"  原始提取的表格 (前5行): {table[:5]}") 

                        if not table or len(table) < 2: 
                            debug_messages.append(f"  表格 {table_idx + 1} 無效 (行數不足或為空)。")
                            continue

                        potential_header_rows = table[0:min(len(table), 5)] 
                        header_row_found = False
                        header = []
                        header_row_start_idx = -1 

                        for h_idx, h_row in enumerate(potential_header_rows):
                            cleaned_h_row_list = [col.replace('\n', ' ').strip() if col is not None else "" for col in h_row]

                            is_potential_header = True
                            for kw in ["學年度", "科目名稱", "學分", "GPA"]: 
                                if not any(kw in cell for cell in cleaned_h_row_list):
                                    is_potential_header = False
                                    break
                            
                            if is_potential_header:
                                header = cleaned_h_row_list
                                header_row_found = True
                                header_row_start_idx = h_idx 
                                break 
                        
                        if not header_row_found:
                            debug_messages.append(f"  未能識別出有效的表頭，跳過此表格。")
                            continue
                        
                        debug_messages.append(f"  識別到的表頭: {header}")

                        col_to_index = {} 
                        index_to_col = {} 

                        for i, h_ext in enumerate(header):
                            if "學年度" in h_ext: col_to_index["學年度"] = i; index_to_col[i] = "學年度"
                            elif "學期" in h_ext: col_to_index["學期"] = i; index_to_col[i] = "學期"
                            elif "選課代號" in h_ext: col_to_index["選課代號"] = i; index_to_col[i] = "選課代號"
                            elif "科目名稱" in h_ext: col_to_index["科目名稱"] = i; index_to_col[i] = "科目名稱"
                            elif "學分" in h_ext: col_to_index["學分"] = i; index_to_col[i] = "學分"
                            elif "GPA" in h_ext: col_to_index["GPA"] = i; index_to_col[i] = "GPA"
                        
                        critical_cols_found = all(col in col_to_index for col in ["學年度", "科目名稱", "學分", "GPA"])
                        debug_messages.append(f"  關鍵列索引映射狀態: {critical_cols_found}")
                        if not critical_cols_found: 
                            debug_messages.append("  缺少關鍵表頭，跳過此表格。")
                            continue

                        學年度_idx = col_to_index.get("學年度")
                        科目名稱_idx = col_to_index.get("科目名稱")
                        學分_idx = col_to_index.get("學分")
                        GPA_idx = col_to_index.get("GPA")

                        processed_rows = []
                        current_row_data = None 
                        
                        for row_num_in_table, row in enumerate(table[header_row_start_idx + 1:]): 
                            cleaned_row = [c.replace('\n', ' ').strip() if c is not None else "" for c in row]
                            
                            debug_messages.append(f"    原始數據行 {row_num_in_table}: {row}") # 打印原始行
                            debug_messages.append(f"    清洗後數據行 {row_num_in_table}: {cleaned_row}") # 打印清洗後行

                            is_new_grade_row = False
                            if 學年度_idx is not None and len(cleaned_row) > 學年度_idx:
                                # 檢查學年度是否為數字且長度為3，且不為空字串
                                if cleaned_row[學年度_idx].isdigit() and len(cleaned_row[學年度_idx]) == 3:
                                    is_new_grade_row = True
                                # 增加對 "抵免" 或 "通過" 的學年度判斷，但通常它們不在學年度列
                                # 這裡的邏輯是基於學年度列的，不需要特別為抵免調整
                                # 只需要確保不是空行
                                elif cleaned_row[學年度_idx].strip() == '': # 如果學年度為空，可能是續行或垃圾行
                                    pass # 讓它進入續行判斷

                            if is_new_grade_row:
                                if current_row_data:
                                    processed_rows.append(current_row_data)
                                current_row_data = list(cleaned_row)
                            elif current_row_data: # 是續行或空行
                                # 判斷是否為「科目名稱」的續行 (學年度為空，且科目名稱有內容)
                                is_subject_continuation = (科目名稱_idx is not None and 
                                                           len(cleaned_row) > 科目名稱_idx and 
                                                           cleaned_row[科目名稱_idx].strip() != '')
                                
                                # 處理 GPA 欄位多行合併的續行
                                is_gpa_continuation = (GPA_idx is not None and 
                                                       len(cleaned_row) > GPA_idx and 
                                                       cleaned_row[GPA_idx].strip() != '')
                                
                                if is_subject_continuation:
                                    current_row_data[科目名稱_idx] += " " + cleaned_row[科目名稱_idx]
                                elif is_gpa_continuation:
                                    current_row_data[GPA_idx] += " " + cleaned_row[GPA_idx]
                                elif not any(c.strip() for c in cleaned_row): # 如果是完全空白的行，結束當前行處理
                                    if current_row_data:
                                        processed_rows.append(current_row_data)
                                    current_row_data = None
                                else: # 不符合新行或續行的模式，但也不是完全空白，可能是其他雜訊，結束當前行處理
                                    if current_row_data:
                                        processed_rows.append(current_row_data)
                                    current_row_data = None
                            else: # current_row_data 為 None，且不是新行，直接忽略
                                pass # 繼續尋找下一個新行

                        if current_row_data: 
                            processed_rows.append(current_row_data)

                        debug_messages.append(f"  處理後有效行數: {len(processed_rows)}")
                        debug_messages.append(f"  處理後部分數據 (前5行): {processed_rows[:5]}")

                        if processed_rows:
                            df_table = pd.DataFrame(processed_rows)
                            df_table.rename(columns=index_to_col, inplace=True)
                            
                            for col_name in expected_columns_order:
                                if col_name not in df_table.columns:
                                    df_table[col_name] = pd.NA
                            
                            df_table = df_table[expected_columns_order].copy()
                            
                            for col in df_table.columns:
                                df_table[col] = df_table[col].astype(str).str.strip().replace('None', '').replace('nan', '')

                            all_grades_data.append(df_table)
                        else:
                            debug_messages.append(f"  此表格未能提取到任何有效數據行。") # 新增此行

                    debug_info_placeholder.text("\n".join(debug_messages)) 

            if not all_grades_data:
                st.warning("未能從 PDF 中提取有效的成績數據。請檢查 PDF 格式或調整表格提取設定。")
                full_grades_df = pd.DataFrame(columns=expected_columns_order)
                return

            full_grades_df = pd.concat(all_grades_data, ignore_index=True)

            full_grades_df.dropna(how='all', inplace=True)

            initial_rows = len(full_grades_df)
            full_grades_df = full_grades_df[
                full_grades_df['學年度'].astype(str).str.match(r'^\d{3}$')
            ]
            debug_messages.append(f"原始數據行數: {initial_rows}, 經過學年度篩選後: {len(full_grades_df)}")

            if '科目名稱' in full_grades_df.columns:
                full_grades_df = full_grades_df[~full_grades_df['科目名稱'].astype(str).str.contains('勞作成績', na=False)]
                debug_messages.append(f"過濾勞作成績後行數: {len(full_grades_df)}")
            
            full_grades_df['GPA'] = full_grades_df['GPA'].astype(str).str.strip()


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
        finally: 
            debug_info_placeholder.text("\n".join(debug_messages))

if __name__ == "__main__":
    main()
