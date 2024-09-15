import pandas as pd

# Define initial data based on Exhibit 2.11
criteria = ['New Products', 'Customer Relations', 'Supplier Relations', 'Success Probability']
weights = [10, 8, 5, 9]  # Initial weights

# Define the project scores (example scores, replace with actual values)
project_scores = {
    'Project A': [5, 3, 5, 2],
    'Project B': [5, 2, 3, 5],
    'Project C': [1, 5, 3, 3],
    'Project D': [2, 4, 1, 2]
}

project_scores_1 = {
    'Project A': [5, 2, 3, 5],
    'Project B': [5, 3, 5, 2],
    'Project C': [1, 5, 3, 3],
    'Project D': [2, 4, 1, 2]
}
# Create a DataFrame to store scores and calculate weighted scores
df = pd.DataFrame(project_scores, index=criteria)

# Calculate weighted scores for each project
df_weighted = df.mul(weights, axis=0)

# Calculate the total weighted score for each project
df_weighted.loc['Total'] = df_weighted.sum(axis=0)

# Save the initial prioritization matrix to Excel
output_file = 'Project_Prioritization_Exhibit2.12.xlsx'
with pd.ExcelWriter(output_file, engine='openpyxl') as writer:
    df_weighted.to_excel(writer, sheet_name='Initial Matrix Exhibit 2.12')
    print("\nInitial Prioritization Matrix:")
    print(df_weighted)
    print("Project Ranking:", df_weighted.loc['Total'].sort_values(ascending=False))

# Function to calculate and save updated matrix based on new weights
def update_weights(new_product_weight, customer_relations_weight, writer):
    # Update the weights
    new_weights = [new_product_weight, customer_relations_weight, 5, 5]
    df_weighted_updated = df.mul(new_weights, axis=0)
    df_weighted_updated.loc['Total'] = df_weighted_updated.sum(axis=0)
    
    # Save the updated matrix to Excel
    df_weighted_updated.to_excel(writer, sheet_name='Matrix Exhibit 2.12')
    print("\nUpdated Prioritization Matrix:")
    print(df_weighted_updated)
    print("Project Ranking:", df_weighted_updated.loc['Total'].sort_values(ascending=False))

# Save the updated weights to the Excel file
with pd.ExcelWriter(output_file, engine='openpyxl', mode='a') as writer:
    # Step 2: Adjust weights (New Product = 3, Customer Relations = 10)
    update_weights(3, 10, writer)

# Step 3: Add IRR to the prioritization matrix
# Define IRR scores for each project and its weight
irr_scores = [1, 4, 3, 5]  # Converted IRR scores: A (5%) = 1, B (10%) = 4, C (8%) = 3, D (14%) = 5
irr_weight = 8

# Add IRR row to the existing DataFrame
df.loc['IRR'] = irr_scores

# Update weights to include IRR
updated_weights = [10, 8, 5, 9, irr_weight]  # Original weights + IRR weight
df_weighted_final = df.mul(updated_weights, axis=0)

# Calculate total weighted score including IRR
df_weighted_final.loc['Total'] = df_weighted_final.sum(axis=0)

# Save the final matrix with IRR included to Excel
with pd.ExcelWriter(output_file, engine='openpyxl', mode='a') as writer:
    df_weighted_final.to_excel(writer, sheet_name='Final Matrix')
    print("\nFinal Prioritization Matrix with IRR for Exhibit 2.11 :")
    print(df_weighted_final)
    print("Final Project Ranking:", df_weighted_final.loc['Total'].sort_values(ascending=False))

print(f"\nResults saved to {output_file}")
