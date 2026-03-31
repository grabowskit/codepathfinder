# Use an official Python runtime as a parent image
FROM python:3.9-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file into the container at /app
COPY requirements.txt /app/

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the current directory contents into the container at /app
COPY . /app/

# Collect static files
RUN DATABASE_URL=sqlite:///dummy.db python manage.py collectstatic --noinput

# Expose port 8000
EXPOSE 8000

# Run manage.py runserver
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
