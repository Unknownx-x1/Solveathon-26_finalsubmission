---
title: Chota Dhobi
emoji: 🧺
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
---

# Chota Dhobi - Laundry Management System

This repository contains the backend and frontend for the Chota Dhobi laundry management system.

## Hugging Face Hosting Instructions

This application is configured to run automatically as a **Docker Space** on Hugging Face Spaces.

### How to deploy to Hugging Face Spaces:

1. Create a new Space on [Hugging Face](https://huggingface.co/spaces).
2. Choose **Docker** as the Space SDK and choose **Blank**.
3. Push the contents of this repository to the remote repository provided by Hugging Face.
   Alternatively, you can just connect your GitHub repository and Hugging Face will automatically build it.
4. Set up your **Space Secrets** on Hugging Face (Settings -> Secrets) for your application variables:
   - `DATABASE_URL` or `POSTGRES_URL` (Since Hugging Face Spaces doesn't provide a persistent database out of the box, you must host your PostgreSQL database on a remote provider like Supabase, Neon, or Aiven and place the connection string here).
   - `SECRET_KEY` (Used for Flask sessions and auth, set to a random secure string)
5. Hugging Face Spaces will automatically build the `Dockerfile`, install the dependencies via `requirements.txt`, and start your application on port 7860 using Gunicorn.

Note: By default, this app will run an in-memory SQLite database if not provided with a persistent Postgres database URL. Due to Hugging Face Spaces resetting containers on sleep, a persistent SQL database like Postgres is highly recommended!
