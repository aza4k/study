# StuDy

[![HTML Badge](https://img.shields.io/badge/Language-HTML-orange.svg)]()
[![Django Badge](https://img.shields.io/badge/Framework-Django-green.svg)]()
[![Tailwind CSS Badge](https://img.shields.io/badge/Style-Tailwind%20CSS-blue.svg)]()
[![Python Badge](https://img.shields.io/badge/Language-Python-yellow.svg)]()


StuDy is an AI-powered learning platform designed to provide personalized and engaging educational experiences. It leverages Django for backend development, Tailwind CSS for styling, and integrates with Google's Gemini AI to generate custom courses on demand. The platform supports multiple languages and offers features such as progress tracking, gamification, and certificate generation.

## Table of Contents

1.  [Features](#features)
2.  [Tech Stack](#tech-stack)
3.  [Installation](#installation)
4.  [Usage](#usage)
5.  [Project Structure](#project-structure)
6.  [API Reference](#api-reference)
7.  [Contributing](#contributing)
8.  [License](#license)
9.  [Important Links](#important-links)
10. [Footer](#footer)

## ✨ Features

*   **AI-Powered Course Generation:** Generate custom courses on any topic using Google's Gemini AI.
*   **Multi-Language Support:** Learn in multiple languages, including English, Russian, and Qaraqalpaqsha.
*   **User Authentication:** Secure registration and login functionality with custom user models.
*   **Gamification:** Earn XP, track progress on a leaderboard, and unlock achievements.
*   **Certificate Generation:** Generate professional PDF certificates upon course completion.
*   **Progress Tracking:** Monitor your learning progress with detailed analytics.
*   **Chatbot Assistance:** AI chatbot that helps with lesson content, integrated into lesson detail view.

## 💻 Tech Stack

*   **Backend:** Django 5.2.8
*   **Frontend:** HTML, Tailwind CSS
*   **AI Integration:** Google Generative AI (Gemini)
*   **Languages:** Python, HTML, Markdown
*   **Other:** python-dotenv, Pillow, JavaScript

## 🛠️ Installation

1.  **Clone the repository:**

    ```bash
    git clone https://github.com/aza4k/study.git
    cd study
    ```

2.  **Create a virtual environment:**

    ```bash
    python -m venv venv
    source venv/bin/activate  # On Linux/macOS
    venv\Scripts\activate  # On Windows
    ```

3.  **Install dependencies:**

    ```bash
    pip install -r requirements.txt
    ```

4.  **Set up environment variables:**
    *   Create a `.env` file in the project root.
    *   Add your Django `SECRET_KEY` and Gemini API Key `GEMINI_API_KEY` to the `.env` file.

        ```
        SECRET_KEY=your_django_secret_key
        GEMINI_API_KEY=your_gemini_api_key
        DEBUG=True # Set to False in production
        ```

5.  **Apply migrations:**

    ```bash
    python manage.py migrate
    ```

6.  **Create a superuser:**

    ```bash
    python manage.py createsuperuser
    ```

7.  **Collect static files:**

    ```bash
    python manage.py collectstatic
    ```

8.  **Run the development server:**

    ```bash
    python manage.py runserver
    ```

## 📝 Usage

1.  **Access the platform:**
    *   Open your web browser and go to `http://127.0.0.1:8000/`.

2.  **Register or log in:**
    *   Create a new account or log in with an existing account.

3.  **Generate a course:**
    *   Navigate to the `/chatbot/` page.
    *   Enter a topic in the chat input and send the message.
    *   Once the topic is clear, click the "Generate Course" button.

4.  **Access the dashboard:**
    *   Go to the `/dashboard/` page to see your enrolled courses.

5.  **Start learning:**
    *   Click on a course to view its modules and lessons.
    *   Complete lessons and quizzes to earn XP and track progress.

6. **AI Chatbot Assistance during Lessons:**
    * During lessons, use the AI assistant to ask questions and clarify the content
    * Access the chatbot panel from the bottom left corner
    * The Chatbot can not be used to answer quiz questions, it is only meant to clarify lesson content

### Additional Information

* The `UserLanguageMiddleware` automatically activates the user's preferred language based on their profile settings.
* To change the language, use the language selector in the navigation bar.

#### Fix Broken Translations

If you encounter any issues with translations, you can run the `get_fix.py` script to fix broken translation files:

```bash
python get_fix.py
```

This script will automatically detect and fix any files with `plural=EXPRESSION` and then recompile the messages.

## 📂 Project Structure

```
study/
├── config/
│   ├── __init__.py
│   ├── asgi.py
│   ├── settings.py
│   ├── urls.py
│   └── wsgi.py
├── core/
│   ├── __init__.py
│   ├── admin.py
│   ├── apps.py
│   ├── certificate.py
│   ├── forms.py
│   ├── management/
│   │   └── commands/
│   │       └── fix_quiz_answers.py
│   ├── middleware.py
│   ├── migrations/
│   │   ├── 0001_initial.py
│   │   ├── 0002_alter_quiz_lesson.py
│   │   ├── 0003_alter_course_created_at_alter_course_description_and_more.py
│   │   └── __init__.py
│   ├── models.py
│   ├── services.py
│   ├── tests.py
│   ├── urls.py
│   └── views.py
├── locale/
│   ├── en/
│   │   └── LC_MESSAGES/
│   │       └── django.po
│   ├── kaa/
│   │   └── LC_MESSAGES/
│   │       └── django.po
│   └── ru/
│       └── LC_MESSAGES/
│           └── django.po
├── templates/
│   ├── base.html
│   ├── chatbot.html
│   ├── course_detail.html
│   ├── dashboard.html
│   ├── gamification.html
│   ├── landing.html
│   ├── lesson.html
│   ├── login.html
│   ├── partials/
│   │   ├── lesson_chatbot_message.html
│   │   └── quiz_result.html
│   ├── pricing.html
│   └── register.html
├── .env
├── manage.py
├── requirements.txt
└── get_fix.py
```

*   `config/`: Django project settings and configuration.
*   `core/`: Core application logic, models, views, forms, and services.
*   `locale/`: Translation files for i18n.
*   `templates/`: HTML templates for the user interface.
*   `requirements.txt`: List of Python dependencies.
*   `.env`: Environment variables for local development.
*   `manage.py`: Django management script.
*   `get_fix.py`: Script to fix broken translation files.

## 💡 API Reference

The `core.services` module provides the following key functions:

*   `chatbot_response(user_message, chat_history, language='en')`: Generates a chatbot response using the Gemini API.

    *   `user_message` (str): The user's input message.
    *   `chat_history` (QuerySet): Chat history for context.
    *   `language` (str): The preferred language for the response.

*   `generate_course_from_ai(topic, language='en', user=None)`: Generates a course structure using the Gemini API and saves it to the database.
    *   `topic` (str): The topic for the course.
    *   `language` (str): The language for the course content.
    *   `user` (CustomUser, optional): The user to enroll in the course.

#### Important

To use Google's Gemini AI, you must have a valid API key in your `.env` file.

## 🤝 Contributing

Contributions are welcome! Please follow these steps:

1.  Fork the repository.
2.  Create a new branch for your feature or bug fix.
3.  Make your changes and commit them with descriptive messages.
4.  Push your changes to your fork.
5.  Submit a pull request to the main branch of the original repository.

## 📜 License

This project has no license.

## 🔗 Important Links

*   **Repository:** [https://github.com/aza4k/study](https://github.com/aza4k/study)
*   **Author:** [https://github.com/aza4k](https://github.com/aza4k)

## <footer>

**StuDy - AI-Powered Learning Platform** | [https://github.com/aza4k/study](https://github.com/aza4k/study)

Made with ❤️ by [aza4k](https://github.com/aza4k). Fork it, like it, star it, raise issues!
</footer>
