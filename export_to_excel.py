#!/usr/bin/env python3
import json
import sys
import os
from datetime import datetime
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
import requests

def export_to_excel():
    """Export all database tables to a single Excel file with one sheet per table"""
    
    print("📊 Fetching data from database...")
    
    # Fetch data from the API
    response = requests.get('https://srms-api.jamesmoriarty.in/api/google-sheets/export-json')
    
    if response.status_code != 200:
        print(f"❌ Error fetching data: {response.status_code}")
        return None
    
    data = response.json()
    
    if data.get('status') != 'success':
        print(f"❌ API error: {data.get('message', 'Unknown error')}")
        return None
    
    tables = data.get('data', {})
    
    # Create Excel workbook
    wb = Workbook()
    
    # Remove default sheet
    default_sheet = wb.active
    wb.remove(default_sheet)
    
    print("\n📋 Creating Excel sheets...")
    
    for table_name, rows in tables.items():
        print(f"  📝 Processing {table_name}...")
        
        # Create a new sheet
        ws = wb.create_sheet(title=table_name[:31])  # Excel sheet name max 31 chars
        
        if rows and len(rows) > 0:
            # Get column headers
            headers = list(rows[0].keys())
            
            # Write headers
            for col_idx, header in enumerate(headers, 1):
                cell = ws.cell(row=1, column=col_idx, value=header)
                cell.font = Font(bold=True)
                cell.fill = PatternFill(start_color="D3D3D3", end_color="D3D3D3", fill_type="solid")
                cell.alignment = Alignment(horizontal="center")
            
            # Write data rows
            for row_idx, row in enumerate(rows, 2):
                for col_idx, header in enumerate(headers, 1):
                    value = row.get(header, '')
                    if value is None:
                        value = ''
                    ws.cell(row=row_idx, column=col_idx, value=value)
            
            # Auto-adjust column widths
            for col in ws.columns:
                max_length = 0
                column = col[0].column_letter
                for cell in col:
                    try:
                        if len(str(cell.value)) > max_length:
                            max_length = len(str(cell.value))
                    except:
                        pass
                adjusted_width = min(max_length + 2, 50)
                ws.column_dimensions[column].width = adjusted_width
            
            print(f"    ✅ {len(rows)} rows written")
        else:
            ws.cell(row=1, column=1, value="No data")
            print(f"    ⚠️ Empty table")
    
    # Generate filename with timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"/home/ubuntu/srms/srms_export_{timestamp}.xlsx"
    
    # Save the workbook
    wb.save(filename)
    print(f"\n✅ Excel file saved: {filename}")
    
    return filename

if __name__ == "__main__":
    export_to_excel()
