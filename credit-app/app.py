import streamlit as st
import pandas as pd
import pdfplumber
import collections
import re # 引入正則表達式模組

# --- 輔助函數 ---
def normalize_text(cell_content):
    """
    標準化從 pdfplumber 提取的單元格內容。
    處理 None 值、pdfplumber 的 Text 物件和普通字串。
    """
    if cell_content is None:
        return ""

    if hasattr(cell_content, 'text'):
        return str(cell_content.text).strip()
    elif isinstance(cell_content, str):
        return cell_content.strip()
    else:
        return str(cell_content).strip()

def make_unique_columns(columns_list):
    """
    將列表中的欄位名稱轉換為唯一的名稱，處理重複和空字串。
    如果遇到重複或空字串，會添加後綴 (例如 'Column_1', '欄位_2')。
    """
    seen = collections.defaultdict(int)
    unique_columns = []
    for col in columns_list:
        # 更精確地處理可能的空白欄位或難以識別的欄位
        original_col = col.strip() if col else "" # 確保處理 None 或空字串
        if not original_col: # 如果清理後還是空的，給個通用名稱
            original_col = f"Column_{len(unique_columns) + 1}"
            
        name = original_col
        if seen[name] > 0:
            name = f"{original_col}_{seen[original_col]}"
        while name in unique_columns:
             seen[original_col] += 1
             name = f"{original_col}_{seen[original_col]}"
        
        unique_columns.append(name)
        seen[original_col] += 1
    return unique_columns

def calculate_total_credits(df_list):
    """
    從提取的 DataFrames 列表中計算總學分。
    尋找包含 '學分' 或 '學分(GPA)' 類似字樣的欄位進行加總。
    """
    total_credits = 0.0
    
    st.subheader("學分計算分析")

    # 定義可能的學分欄位名稱關鍵字，根據實際 PDF 格式調整
    # 謝雲瑄的PDF中，學分欄位是 '學\n\n\n分'，經過normalize_text可能是 '學分' 或 '學 分'
    # 邱旭廷的PDF中，學分欄位是 '學分'
    credit_column_keywords = ["學分", "學分數", "學分(GPA)", "學 分"] #
    
    # 用於從可能包含GPA的字符串中提取數字學分，例如 "A 2" -> 2
    # 匹配數字 (整數或浮點數)，可以是獨立的數字，也可以在字串末尾
    credit_pattern = re.compile(r'(\d+(\.\d+)?)\s*$') 

    for df_idx, df in enumerate(df_list):
        st.write(f"--- 分析表格 {df_idx + 1} ---")
        st.write(f"偵測到的欄位名稱: `{list(df.columns)}`") # 輸出偵測到的所有欄位名稱

        found_credit_column = None
        for col in df.columns:
            # 更加激進的清理，只保留中文、英文、數字、括號（針對GPA）
            # 移除非數字字母中文字符，並移除括號內內容用於關鍵字匹配，但保留原始列名
            cleaned_col_for_match = "".join(char for char in col if '\u4e00' <= char <= '\u9fa5' or 'a' <= char <= 'z' or 'A' <= char <= 'Z' or '0' <= char <= '9' or char in '()').strip()
            
            # 檢查是否包含關鍵字
            if any(keyword in cleaned_col_for_match for keyword in credit_column_keywords):
                found_credit_column = col # 使用原始的欄位名稱
                break
        
        if found_credit_column:
            st.info(f"從表格 {df_idx + 1} (原始欄位: '{found_credit_column}') 偵測到學分數據。")
            try:
                processed_credits = []
                for item in df[found_credit_column]:
                    item_str = str(item).strip()
                    # 嘗試用正則表達式從字串末尾提取數字
                    match = credit_pattern.search(item_str)
                    if match:
                        try:
                            processed_credits.append(float(match.group(1)))
                        except ValueError:
                            processed_credits.append(0.0) # 如果無法轉換為數字，計為0
                    else:
                        processed_credits.append(0.0) # 如果沒有匹配到數字，計為0

                credits = pd.Series(processed_credits)
                
                # 篩選掉 無效的學分 (例如 '通過' 或 '抵免' 這些文字已經在上一處理步驟中變為0)
                valid_credits = credits[credits >= 0] # 包含 0 學分 (例如體育課)
                
                current_table_credits = valid_credits.sum()
                total_credits += current_table_credits
                st.write(f"表格 {df_idx + 1} 的學分總計: **{current_table_credits:.2f}**")
                
            except Exception as e:
                st.warning(f"表格 {df_idx + 1} 的學分欄位 '{found_credit_column}' 轉換為數值時發生錯誤: `{e}`")
                st.warning("該表格的學分可能無法計入總數。請檢查學分欄位數據是否為純數字或可提取數字。")
        else:
            st.info(f"表格 {df_idx + 1} 未偵測到明確的學分欄位。檢查欄位：`{list(df.columns)}`。不計入總學分。")
            
    return total_credits

def process_pdf_file(uploaded_file):
    """
    使用 pdfplumber 處理上傳的 PDF 檔案，提取表格。
    """
    all_grades_data = []

    try:
        with pdfplumber.open(uploaded_file) as pdf:
            st.write(f"正在處理檔案: **{uploaded_file.name}**")
            num_pages = len(pdf.pages)
            st.info(f"PDF 總頁數: **{num_pages}**")

            for page_num, page in enumerate(pdf.pages):
                st.subheader(f"頁面 {page_num + 1}")

                table_settings = {
                    "vertical_strategy": "lines",
                    "horizontal_strategy": "lines",
                    "snap_tolerance": 3,
                    "join_tolerance": 3,
                    "edge_min_length": 3,
                    "text_tolerance": 1,
                }

                try:
                    tables = page.extract_tables(table_settings)

                    if not tables:
                        st.warning(f"頁面 **{page_num + 1}** 未偵測到表格。這可能是由於 PDF 格式複雜或表格提取設定不適用。")
                        continue

                    for table_idx, table in enumerate(tables):
                        st.markdown(f"**頁面 {page_num + 1} 的表格 {table_idx + 1}**")
                        
                        processed_table = []
                        for row in table:
                            # 確保每個單元格都經過 normalize_text 處理
                            normalized_row = [normalize_text(cell) for cell in row]
                            processed_table.append(normalized_row)
                        
                        if not processed_table:
                            st.info(f"表格 **{table_idx + 1}** 提取後為空。")
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
                                # 這是修正 IndentationError 的關鍵部分：確保 `if/elif/else` 區塊內部有縮排
                                if len(row) > num_columns_header:
                                    cleaned_data_rows.append(row[:num_columns_header])
                                elif len(row) < num_columns_header: # 這一行就是之前報錯的 153 行
                                    cleaned_data_rows.append(row + [''] * (num_columns_header - len(row)))
                                else:
                                    cleaned_data_rows.append(row)

                            try:
                                df_table = pd.DataFrame(cleaned_data_rows, columns=unique_columns)
                                all_grades_data.append(df_table)
                                st.dataframe(df_table)
                            except Exception as e_df:
                                st.error(f"頁面 {page_num + 1} 表格 {table_idx + 1} 轉換為 DataFrame 時發生錯誤: `{e_df}`")
                                st.error(f"原始處理後數據範例: {processed_table[:2]} (前兩行)")
                                st.error(f"生成的唯一欄位名稱: {unique_columns}")
                        else:
                            st.info(f"表格 **{table_idx + 1}** 沒有數據行。")

                except Exception as e_table:
                    st.error(f"頁面 **{page_num + 1}** 處理表格時發生錯誤: `{e_table}`")
                    st.warning("這可能是由於 PDF 格式複雜或表格提取設定不適用。")

    except pdfplumber.PDFSyntaxError as e_pdf_syntax:
        st.error(f"處理 PDF 語法時發生錯誤: `{e_pdf_syntax}`。檔案可能已損壞或格式不正確。")
    except Exception as e:
        st.error(f"處理 PDF 檔案時發生一般錯誤: `{e}`")
        st.error("請確認您的 PDF 格式是否為清晰的表格。若問題持續，可能是 PDF 結構較為複雜，需要調整 `pdfplumber` 的表格提取設定。")

    return all_grades_data

# --- Streamlit 應用主體 ---
def main():
    st.set_page_config(page_title="PDF 成績單提取與學分計算工具", layout="wide")
    st.title("📄 PDF 成績單表格數據提取與學分計算")

    st.write("請上傳您的 PDF 成績單檔案，工具將嘗試提取其中的表格數據並計算總學分。")

    uploaded_file = st.file_uploader("選擇一個 PDF 檔案", type="pdf")

    if uploaded_file is not None:
        st.success(f"已上傳檔案: **{uploaded_file.name}**")
        with st.spinner("正在處理 PDF，請稍候..."):
            extracted_dfs = process_pdf_file(uploaded_file)

        if extracted_dfs:
            st.success("成功提取所有表格數據！")
            st.write("以下是所有提取到的表格數據 (每個表格作為一個 DataFrame)：")
            
            try:
                # 嘗試將所有 DataFrame 合併，如果欄位名稱不一致，會導致 NaN
                combined_df = pd.concat(extracted_dfs, ignore_index=True)
                st.subheader("所有歷年成績表格合併後的數據 (若結構相容)")
                st.dataframe(combined_df)
                
                # 計算總學分
                total_credits = calculate_total_credits(extracted_dfs)
                st.markdown(f"## 總計學分: **{total_credits:.2f}**")
                st.info("請注意：學分計算是基於偵測到的「學分」欄位加總，並排除「抵免」、「通過」等非數字或非正數學分。")

                # 提供下載選項
                csv_data = combined_df.to_csv(index=False, encoding='utf-8-sig')
                st.download_button(
                    label="下載所有數據為 CSV",
                    data=csv_data,
                    file_name=f"{uploaded_file.name.replace('.pdf', '')}_extracted_data.csv",
                    mime="text/csv",
                )
            except Exception as e_concat:
                st.warning(f"無法將所有提取的表格合併：`{e_concat}`。這通常是因為不同表格的欄位結構或數量不一致。")
                st.info("每個單獨的表格已在上方獨立顯示，您可以查看單獨的表格結果。")
                # 即使合併失敗，也嘗試計算學分
                total_credits = calculate_total_credits(extracted_dfs)
                st.markdown(f"## 總計學分: **{total_credits:.2f}**")
                st.info("請注意：學分計算是基於偵測到的「學分」欄位加總，並排除「抵免」、「通過」等非數字或非正數學分。")
        else:
            st.warning("未從 PDF 中提取到任何表格數據。請檢查 PDF 內容或嘗試調整 `table_settings`。")
    else:
        st.info("請上傳 PDF 檔案以開始處理。")

if __name__ == "__main__":
    main()
