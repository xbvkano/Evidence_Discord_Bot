# Use an official Python runtime as a parent image
FROM python:3.11

# Set the working directory inside the container
WORKDIR /app

# Copy the current directory contents into the container at /app
COPY . .

# Install dependencies from requirements.txt (if you have one)
RUN pip install --no-cache-dir -r requirements.txt

# Set environment variables from .env file
ENV PYTHONUNBUFFERED=1

# Command to run the bot
CMD ["python", "main.py"]
