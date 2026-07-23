# Add this validation in the generate_po_for_supplier function
# Before generating the PO, check if excess_percentage > 5

# Look for this section:
# if excess_percentage > 0:
#     quantity = quantity * (1 + (excess_percentage / 100))

# Replace with:
# if excess_percentage > 0:
#     if excess_percentage > 5:
#         raise ValueError(f"Excess percentage cannot exceed 5%. Current: {excess_percentage}%")
#     quantity = quantity * (1 + (excess_percentage / 100))
