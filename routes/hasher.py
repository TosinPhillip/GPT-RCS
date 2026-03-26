import bcrypt
import pandas as pd

std = pd.read_csv('Documents/students.csv')
print(std.head())
# password = bcrypt.hashpw("gptschool2025".encode('utf-8'), bcrypt.gensalt()).decode('utf-8')