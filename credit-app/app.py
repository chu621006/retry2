import streamlit as st
import pandas as pd
import pdfplumber
import collections
import re 

# --- 輔助函數 ---
# 確保這個函數在任何調用之前定義，處理 None 值、pdfplumber Text 物件和普通字串
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
    返回總學分和計算學分的科目列表。
    """
    total_credits = 0.0
    calculated_courses = [] # 用於存放計算了學分的科目名稱和學分

    # 移除詳細的學分計算分析小標題，保持介面簡潔
    # st.subheader("學分計算分析") 

    # 定義可能的學分欄位名稱關鍵字 (中文和英文)
    credit_column_keywords = ["學分", "學分數", "學分(GPA)", "學 分", "Credits", "Credit"] 
    # 定義可能的科目名稱關鍵字
    subject_column_keywords = ["科目名稱", "課程名稱", "Course Name", "Subject Name", "科目"] 
    
    # 用於從可能包含GPA的字符串中提取數字學分，例如 "A 2" -> 2, "3" -> 3
    credit_pattern = re.compile(r'(\d+(\.\d+)?)') 

    for df_idx, df in enumerate(df_list):
        # 移除每一頁的詳細分析輸出，保持簡潔
        # st.write(f"--- 分析表格 {df_idx + 1} ---")
        # st.write(f"偵測到的原始欄位名稱: `{list(df.columns)}`") 
        
        found_credit_column = None
        found_subject_column = None # 偵測科目名稱欄位
        
        # 步驟 1: 優先匹配明確的學分和科目關鍵字
        for col in df.columns:
            # 清理欄位名，只保留中英文數字，用於匹配關鍵字
            cleaned_col_for_match = "".join(char for char in normalize_text(col) if '\u4e00' <= char <= '\u9fa5' or 'a' <= char <= 'z' or 'A' <= char <= 'Z' or '0' <= char <= '9').strip()
            
            if any(keyword in cleaned_col_for_match for keyword in credit_column_keywords):
                found_credit_column = col 
            if any(keyword in cleaned_col_for_match for keyword in subject_column_keywords):
                found_subject_column = col
            
            # 如果兩個都找到了，就可以提前結束循環
            if found_credit_column and found_subject_column:
                break 

        # 步驟 2: 如果沒有明確匹配，嘗試從通用名稱 (Column_X) 中猜測學分和科目欄位
        if not found_credit_column or not found_subject_column:
            potential_credit_columns = []
            potential_subject_columns = []

            for col in df.columns:
                # 判斷是否為通用欄位名（例如 Column_1）或長度過短
                is_general_col = re.match(r"Column_\d+", col) or len(normalize_text(col).strip()) < 3
                
                # 檢查是否為潛在學分欄位
                # 取前 N 行數據進行判斷，避免空行或表尾總計的干擾 (N=10 比較通用)
                sample_data = df[col].head(10).apply(normalize_text).tolist()
                numeric_like_count = 0
                total_sample_count = len(sample_data)
                
                for item_str in sample_data:
                    if item_str == "通過" or item_str == "抵免" or item_str.lower() in ["pass", "exempt"]: # 兼容英文
                        numeric_like_count += 1
                    else:
                        matches = credit_pattern.findall(item_str)
                        if matches:
                            try:
                                # 嘗試轉換為浮點數，並檢查學分範圍 (例如 0.0 到 10.0)
                                val = float(matches[-1][0])
                                if 0.0 <= val <= 10.0: # 學分通常不會超過 10
                                    numeric_like_count += 1
                            except ValueError:
                                pass
                        # 不匹配數字或特定關鍵字的，不計入 numeric_like_count
                
                # 如果超過一半 (或更高比例) 的樣本數據看起來像學分，則認為可能是學分欄位
                if total_sample_count > 0 and numeric_like_count / total_sample_count >= 0.6: # 提高識別門檻到 60%
                    potential_credit_columns.append(col)
                
                # 檢查是否為潛在科目名稱欄位 (若包含中文且非純數字)
                if is_general_col:
                    subject_like_count = 0
                    for item_str in sample_data:
                        # 判斷是否看起來像科目名稱: 包含中文字符，長度大於3，且不全是數字
                        if re.search(r'[\u4e00-\u9fa5]', item_str) and len(item_str) > 3 and not item_str.isdigit() and not re.match(r'^\d+(\.\d+)?$', item_str): 
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
                # 如果學分欄位已確定，且科目欄位未確定，則選擇學分欄位左側最接近的科目欄位
                if found_credit_column:
                    credit_col_idx = df.columns.get_loc(found_credit_column)
                    min_dist = float('inf')
                    best_subject_candidate = None
                    for p_col in potential_subject_columns:
                        p_col_idx = df.columns.get_loc(p_col)
                        if p_col_idx < credit_col_idx and (credit_col_idx - p_col_idx) < min_dist:
                            min_dist = credit_col_idx - p_col_idx
                            best_subject_candidate = p_col
                    if best_subject_candidate:
                        found_subject_column = best_subject_candidate
                elif potential_subject_columns: # 否則選擇第一個潛在科目欄位
                    found_subject_column = potential_subject_columns[0]

        if found_credit_column:
            # 移除詳細偵測訊息，只保留問題提示
            # st.info(f"從表格 {df_idx + 1} 偵測到學分欄位: '{found_credit_column}'。")
            # if found_subject_column:
            # st.info(f"從表格 {df_idx + 1} 偵測到科目名稱欄位: '{found_subject_column}'。")
            # else:
            # st.warning(f"表格 {df_idx + 1} 未偵測到明確的科目名稱欄位。科目名稱可能無法準確記錄。")

            try:
                current_table_credits = 0.0
                for row_idx, row in df.iterrows():
                    item_str = normalize_text(row[found_credit_column])
                    
                    credit_val = 0.0
                    # 優先處理已知非數字的學分情況
                    if item_str == "通過" or item_str == "抵免" or item_str.lower() in ["pass", "exempt"]:
                        credit_val = 0.0
                    else:
                        # 嘗試用正則表達式從字串中提取所有數字
                        matches = credit_pattern.findall(item_str)
                        if matches:
                            # 假設最後一個數字通常是學分，例如 "A 2" 中的 "2"
                            try:
                                val = float(matches[-1][0])
                                if 0.0 <= val <= 10.0: # 確保提取的數字在合理學分範圍內
                                    credit_val = val
                                else:
                                    credit_val = 0.0 # 超出範圍的數字不計入學分
                            except ValueError:
                                credit_val = 0.0
                        else:
                            credit_val = 0.0 # 沒有匹配到數字
                    
                    if credit_val > 0: # 只記錄有學分的科目
                        current_table_credits += credit_val
                        
                        course_name = "未知科目"
                        if found_subject_column and found_subject_column in row:
                            course_name = normalize_text(row[found_subject_column])
                        
                        calculated_courses.append({"科目名稱": course_name, "學分": credit_val, "來源表格": df_idx + 1})

                total_credits += current_table_credits
                # 移除每個表格的學分總計顯示
                # st.write(f"表格 {df_idx + 1} 的學分總計: **{current_table_credits:.2f}**")
                
            except Exception as e:
                st.warning(f"表格 {df_idx + 1} 的學分欄位 '{found_credit_column}' 轉換為數值時發生錯誤: `{e}`")
                st.warning("該表格的學分可能無法計入總數。請檢查學分欄位數據是否為純數字或可提取數字。")
        else:
            # 移除詳細的偵測不到學分欄位訊息
            # st.info(f"表格 {df_idx + 1} 未偵測到明確的學分欄位。檢查欄位：`{list(df.columns)}`。不計入總學分。")
            pass # 不顯示此類信息，保持介面簡潔
            
    return total_credits, calculated_courses

def process_pdf_file(uploaded_file):
    """
    使用 pdfplumber 處理上傳的 PDF 檔案，提取表格。
    此函數內部將減少 Streamlit 的直接輸出，只返回提取的數據。
    """
    all_grades_data = []

    try:
        with pdfplumber.open(uploaded_file) as pdf:
            # 移除處理檔案和頁數信息，保持介面簡潔
            # st.write(f"正在處理檔案: **{uploaded_file.name}**")
            # num_pages = len(pdf.pages)
            # st.info(f"PDF 總頁數: **{num_pages}**")

            for page_num, page in enumerate(pdf.pages):
                # 移除頁面標題
                # st.subheader(f"頁面 {page_num + 1}") 

                table_settings = {
                    "vertical_strategy": "lines", # 基於線條偵測垂直分隔
                    "horizontal_strategy": "lines", # 基於線條偵測水平分隔
                    "snap_tolerance": 3, # 垂直/水平線的捕捉容忍度
                    "join_tolerance": 3, # 斷開線段的連接容忍度
                    "edge_min_length": 3, # 偵測到的線條最小長度
                    "text_tolerance": 1, # 文本與偵測線條的容忍度 (低於此值則認為文本在線上)
                }
                
                current_page = page 

                try:
                    tables = current_page.extract_tables(table_settings)

                    if not tables:
                        # 仍保留未偵測到表格的警告，因為這是關鍵信息
                        st.warning(f"頁面 **{page_num + 1}** 未偵測到表格。這可能是由於 PDF 格式複雜或表格提取設定不適用。")
                        continue

                    for table_idx, table in enumerate(tables):
                        # 移除每個表格的標題
                        # st.markdown(f"**頁面 {page_num + 1} 的表格 {table_idx + 1}**")
                        
                        processed_table = []
                        # 確保在這裡正確使用 normalize_text 處理所有單元格內容
                        for row in table:
                            normalized_row = [normalize_text(cell) for cell in row]
                            processed_table.append(normalized_row)
                        
                        if not processed_table:
                            # 仍保留空表格信息，幫助偵錯
                            st.info(f"頁面 {page_num + 1} 的表格 **{table_idx + 1}** 提取後為空。")
                            continue

                        # 假設第一行是標題行，但確保有足夠的行
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
                                # 確保行數據與標題長度匹配
                                if len(row) > num_columns_header:
                                    cleaned_data_rows.append(row[:num_columns_header])
                                elif len(row) < num_columns_header:
                                    cleaned_data_rows.append(row + [''] * (num_columns_header - len(row)))
                                else:
                                    cleaned_data_rows.append(row)

                            try:
                                df_table = pd.DataFrame(cleaned_data_rows, columns=unique_columns)
                                all_grades_data.append(df_table)
                                # 這是您希望移除的詳細表格輸出
                                # st.dataframe(df_table) 
                            except Exception as e_df:
                                # 仍保留轉換 DataFrame 的錯誤信息，這很重要
                                st.error(f"頁面 {page_num + 1} 表格 {table_idx + 1} 轉換為 DataFrame 時發生錯誤: `{e_df}`")
                                st.error(f"原始處理後數據範例: {processed_table[:2]} (前兩行)")
                                st.error(f"生成的唯一欄位名稱: {unique_columns}")
                        else:
                            # 仍保留沒有數據行信息
                            st.info(f"頁面 {page_num + 1} 的表格 **{table_idx + 1}** 沒有數據行。")

                except Exception as e_table:
                    # 仍保留處理表格時的錯誤信息
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
            # 移除成功提取所有表格數據的提示，因為下面會有更具體的結果
            # st.success("成功提取所有表格數據！")
            
            total_credits, calculated_courses = calculate_total_credits(extracted_dfs)

            st.markdown("---")
            st.markdown("## ✅ 查詢結果") # 調整為更簡潔的標題
            st.markdown(f"目前總學分: <span style='color:green; font-size: 24px;'>**{total_credits:.2f}**</span>", unsafe_allow_html=True)
            # 移除詳細的提示信息，只保留目標學分相關內容
            # st.info("請注意：學分計算是基於偵測到的「學分」欄位加總，並排除「抵免」、「通過」等非數字或非正數學分。")

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
            st.markdown("### 📚 通過的課程列表") # 調整為更符合截圖的標題
            if calculated_courses:
                # 將科目列表轉換為 DataFrame 以便顯示
                courses_df = pd.DataFrame(calculated_courses)
                # 重新排序欄位以符合截圖的顯示順序 (學期、學年度、科目名稱、學分、GPA)
                # 但原始數據中沒有GPA，所以只顯示已有的
                # 如果需要學期和學年度，需要從原始DataFrame中提取，但這裡只保留科目名稱和學分，並可加上來源表格作為輔助信息
                
                # 為了盡量符合「通過的課程列表」的格式，我們需要確保`calculated_courses`包含學期和學年度。
                # 目前`calculated_courses`只包含`科目名稱`、`學分`和`來源表格`。
                # 要實現完全相同的介面，需要調整`calculate_total_credits`來提取學期和學年度。
                # 但為了維持「其他程式碼都不要動」的原則，我只能用現有的`calculated_courses`結構。
                # 如果後續有需要，可以再告訴我調整`calculate_total_credits`來包含更多原始資訊。

                # 當前數據只有 科目名稱, 學分, 來源表格。為了更像截圖，我們可以這樣呈現：
                # 假設您更希望看到學年度和學期，這需要更深入的邏輯來從原始行中提取這些資訊並加入到 calculated_courses。
                # 但在不「動」其他程式碼的前提下，我會用現有結構來顯示。
                
                # 這裡假設您指的是像 image_f60ac7.png 中那樣的「通過的課程列表」
                # 該列表包含了 學年度、學期、科目名稱、學分、GPA
                # 但我們目前只有科目名稱和學分。若要完全一樣，需要修改 `calculate_total_credits` 來提取更多欄位。
                # 暫時先用現有的`calculated_courses`結構進行展示。
                
                # 可以考慮增加學年度和學期到 `calculated_courses` 中，但這會修改 `calculate_total_credits`。
                # 為了避免過多修改，我們目前只顯示 `科目名稱` 和 `學分`。
                # 重新組織顯示欄位以符合常見成績單習慣
                display_cols = ['科目名稱', '學分']
                if '學年度' in courses_df.columns:
                    display_cols.insert(0, '學年度')
                if '學期' in courses_df.columns:
                    display_cols.insert(1, '學期')
                
                # 確保只包含確實存在的欄位
                final_display_cols = [col for col in display_cols if col in courses_df.columns]
                
                # Streamlit DataFrame 顯示
                st.dataframe(courses_df[final_display_cols], height=300, use_container_width=True) # 使用 use_container_width 讓表格自動調整寬度
            else:
                st.info("沒有找到可以計算學分的科目。")

            # 提供下載選項 
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
