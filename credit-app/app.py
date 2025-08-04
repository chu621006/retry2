import streamlit as st
import pandas as pd
import pdfplumber

# --- 輔助函數 ---
def normalize_text(cell_content):
    """
    標準化從 pdfplumber 提取的單元格內容。
    處理 None 值、pdfplumber 的 Text 物件和普通字串。
    """
    if cell_content is None:
        return ""  # 返回空字串來表示空白單元格

    # 檢查是否為 pdfplumber 的 Text 物件 (通常有 .text 屬性)
    if hasattr(cell_content, 'text'):
        return str(cell_content.text).strip()
    # 如果已經是字串
    elif isinstance(cell_content, str):
        return cell_content.strip()
    else:
        # 對於其他未知類型，嘗試轉換為字串並去除空白
        return str(cell_content).strip()

def process_pdf_file(uploaded_file):
    """
    使用 pdfplumber 處理上傳的 PDF 檔案，提取表格。
    """
    all_grades_data = [] # 初始化用於儲存所有表格數據的列表

    try:
        with pdfplumber.open(uploaded_file) as pdf:
            st.write(f"正在處理檔案: **{uploaded_file.name}**")
            num_pages = len(pdf.pages)
            st.info(f"PDF 總頁數: **{num_pages}**")

            for page_num, page in enumerate(pdf.pages):
                st.subheader(f"頁面 {page_num + 1}")

                # 這裡你可以根據需要調整 table_settings
                # 對於成績單這類有清晰線條的表格，'lines' 策略通常效果不錯。
                # 如果仍有問題，可以嘗試調整容忍度或將策略改為 'text'。
                table_settings = {
                    "vertical_strategy": "lines",
                    "horizontal_strategy": "lines",
                    "snap_tolerance": 3,           # 調整線條捕捉的容忍度
                    "join_tolerance": 3,           # 調整合併線條的容忍度
                    "edge_min_length": 3,          # 最小邊緣長度，避免偵測到過短的線條
                    "text_tolerance": 1,           # 文本接近線條的容忍度
                    # 如果表格線條不明顯，可以嘗試：
                    # "vertical_strategy": "text",
                    # "horizontal_strategy": "text",
                }

                try:
                    # 嘗試提取當前頁面上的所有表格
                    tables = page.extract_tables(table_settings)

                    if not tables:
                        st.warning(f"頁面 **{page_num + 1}** 未偵測到表格。這可能是由於 PDF 格式複雜或表格提取設定不適用。")
                        continue

                    for table_idx, table in enumerate(tables):
                        st.markdown(f"**頁面 {page_num + 1} 的表格 {table_idx + 1}**")
                        
                        # 使用 normalize_text 函數處理每個單元格
                        processed_table = []
                        for row in table:
                            normalized_row = [normalize_text(cell) for cell in row]
                            processed_table.append(normalized_row)
                        
                        # 將處理後的表格轉換為 DataFrame
                        if processed_table and len(processed_table) > 1:
                            # 假設第一行是標題
                            df_table = pd.DataFrame(processed_table[1:], columns=processed_table[0])
                            all_grades_data.append(df_table)
                            st.dataframe(df_table)
                        elif processed_table:
                             # 如果只有一行或沒有明確標題，直接作為數據
                             df_table = pd.DataFrame(processed_table)
                             all_grades_data.append(df_table)
                             st.dataframe(df_table)
                        else:
                            st.info(f"表格 **{table_idx + 1}** 提取後為空。")

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
    st.set_page_config(page_title="PDF 成績單提取工具", layout="wide")
    st.title("📄 PDF 成績單表格數據提取")

    st.write("請上傳您的 PDF 成績單檔案，工具將嘗試提取其中的表格數據。")

    uploaded_file = st.file_uploader("選擇一個 PDF 檔案", type="pdf")

    if uploaded_file is not None:
        st.success(f"已上傳檔案: **{uploaded_file.name}**")
        st.spinner("正在處理 PDF，請稍候...")
        
        # 處理 PDF 檔案
        extracted_dfs = process_pdf_file(uploaded_file)

        if extracted_dfs:
            st.success("成功提取所有表格數據！")
            st.write("以下是所有提取到的表格數據 (每個表格作為一個 DataFrame)：")
            
            # 你可以選擇如何合併或顯示這些 DataFrame
            # 例如，將它們合併成一個大的 DataFrame (如果結構相容)
            try:
                combined_df = pd.concat(extracted_dfs, ignore_index=True)
                st.subheader("所有表格合併後的數據 (若結構相容)")
                st.dataframe(combined_df)
                
                # 提供下載選項
                csv_data = combined_df.to_csv(index=False, encoding='utf-8-sig')
                st.download_button(
                    label="下載所有數據為 CSV",
                    data=csv_data,
                    file_name=f"{uploaded_file.name.replace('.pdf', '')}_extracted_data.csv",
                    mime="text/csv",
                )
            except Exception as e_concat:
                st.warning(f"無法將所有提取的表格合併：`{e_concat}`。可能因為表格結構不一致。")
                st.info("每個單獨的表格已在上方獨立顯示。")
        else:
            st.warning("未從 PDF 中提取到任何表格數據。請檢查 PDF 內容或嘗試調整 `table_settings`。")
    else:
        st.info("請上傳 PDF 檔案以開始處理。")

if __name__ == "__main__":
    main()
