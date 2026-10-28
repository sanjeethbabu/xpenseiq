### Additional Requirements — Invoice Intelligence

1. **Complete Invoice Extraction:** Extract all available fields, including invoice number, invoice date, due date, currency, seller and buyer names, billing and shipping addresses, seller and buyer GSTINs, place of supply, document type, payment terms, and other relevant invoice metadata.

2. **Line-Item Extraction:** Store each line item as a separate database record. Capture description, HSN/SAC code when available, quantity, unit of measurement, unit price, discount, taxable amount, applicable GST rate, CGST, SGST, IGST, cess, and line total where available.

3. **Invoice Totals:** Capture subtotal, total discounts, taxable value, tax totals, round-off, shipping or other charges, and final invoice total. Support invoices with different GST structures and invoices that do not contain GST.

4. **Open-Source Document Processing:** Use PyMuPDF for text-based PDFs and Tesseract OCR for scanned PDFs and receipt images. Use Groq API with a compatible model to interpret extracted text and produce schema-constrained structured output. Do not assume every Groq model supports image input.

5. **Validation:** Validate data types, required fields, monetary precision, line-item totals, tax calculations, and invoice totals using deterministic backend code. Flag missing, uncertain, or inconsistent values for user review. Never silently invent missing values.

6. **Duplicate Detection:** Detect possible duplicate invoices using user ownership, seller GSTIN, invoice number, invoice date, and invoice total. Use normalized matching and appropriate database constraints where suitable. Flag potential duplicates for review rather than automatically deleting records.

7. **Database Persistence:** Store invoices, invoice line items, tax details, sellers, buyers where appropriate, and linked expense records in normalized PostgreSQL tables with foreign keys and indexes. Persist confirmed structured data, not permanent copies of original documents by default.

8. **Search and Reports:** Provide search and filtering by invoice number, seller, buyer, GSTIN, date range, amount, category, and processing status. Generate expense summaries, GST breakdowns, monthly reports, and CSV exports from actual database records.

9. **Review Interface:** Display extracted invoice data and line items in an editable review screen. Allow users to correct extraction errors and confirm records before finalizing them.

10. **Testing:** Include test invoices covering GST and non-GST invoices, CGST/SGST and IGST, multiple line items, scanned documents, missing fields, incorrect totals, and duplicate invoices.