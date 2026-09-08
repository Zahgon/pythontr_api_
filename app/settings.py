"""
Settings for the app project.

This is a plain module: import it and read the names.  Every name the
application reads at runtime lives here, and the routers read it through
``from app import settings`` rather than through a settings registry.
"""

import os
import sys

from app.i18n import gettext_lazy as _
from dotenv import load_dotenv


load_dotenv()

# Build paths inside the project like this: os.path.join(BASE_DIR, ...)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# Quick-start development settings - unsuitable for production

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = 's#kkb7z3ste9!7fo#__7jq*ey5+ro_$ho83b=4@ziw&!9=_h86'

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.environ.get('DEBUG', '').lower() == 'true'

ALLOWED_HOSTS = os.environ.get('ALLOW_HOST', '').split(',')

LANGUAGE_CODE = 'tr'

LANGUAGES = [
    ('tr', _('turkish')),
    ('en', _('english')),
]

LOCALE_PATHS = [
    os.path.join(BASE_DIR, 'locale'),
]

# Application definition
INSTALLED_APPS = [
    'app',
    'core',
    'user',
    'recipe',
]

API = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'app.authentication.CookieTokenAuthentication',
        'app.authentication.TokenAuthentication',  # Geriye dönük uyumluluk
    ],
}

TOKEN_EXPIRED_AFTER_SECONDS = 86400

if 'test' not in sys.argv:
    API['DEFAULT_PAGINATION_CLASS'] = 'core.pagination.CustomPagination'
    API['PAGE_SIZE'] = 27

RECAPTCHA_URL = 'https://www.google.com/recaptcha/api/siteverify'
RECAPTCHA_SITE_KEY = os.environ.get('RECAPTCHA_SITE_KEY')
RECAPTCHA_SECRET_KEY = os.environ.get('RECAPTCHA_SECRET_KEY')

MIDDLEWARE = [
    'app.middleware.SecurityMiddleware',
    'app.middleware.SessionMiddleware',
    'app.middleware.CommonMiddleware',
    'app.middleware.CsrfViewMiddleware',
    'app.middleware.AuthenticationMiddleware',
    'app.middleware.MessageMiddleware',
    'app.middleware.XFrameOptionsMiddleware',
    'app.middleware.LocaleMiddleware',
]

ROOT_URLCONF = 'app.urls'

ASGI_APPLICATION = 'app.main:app'


# Database

DATABASES = {
    'default': {
        'ENGINE': os.environ.get('DB_ENGINE'),
        'HOST': os.environ.get('DB_HOST'),
        'NAME': os.environ.get('DB_NAME'),
        'USER': os.environ.get('DB_USER'),
        'PASSWORD': os.environ.get('DB_PASS'),
    }
}

SITE_URL = os.environ.get('SITE_URL', 'http://localhost:8000')

EMAIL_BACKEND = os.environ.get(
    'EMAIL_BACKEND', 'app.mail.backends.smtp.EmailBackend')
EMAIL_HOST = os.environ.get('EMAIL_HOST')
EMAIL_PORT = int(os.environ.get('EMAIL_PORT', 25))
EMAIL_USE_TLS = os.environ.get('EMAIL_USE_TLS', '').lower() == 'true'
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD')
DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL')


# Password validation
#
# Configured exactly as the baseline configured it.  Nothing reads this
# list -- the baseline never wired a validator into the create/update
# paths either, and that behaviour is preserved on purpose.

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'app.validators.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'app.validators.MinimumLengthValidator',
    },
    {
        'NAME': 'app.validators.CommonPasswordValidator',
    },
    {
        'NAME': 'app.validators.NumericPasswordValidator',
    },
]


# Internationalization

# LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_L10N = True

USE_TZ = True

APPEND_SLASH = True

X_FRAME_OPTIONS = 'DENY'


# Static files (CSS, JavaScript, Images)


STATIC_URL = '/static/'
# STATIC_ROOT = 'static/'

STATICFILES_DIRS = (
    os.path.join(BASE_DIR, "static"),
)

AVATAR_ROOT = 'static/avatar/'
ARTICLE_ROOT = 'static/article/'
IMAGE_ROOT = 'static/img/'

APLICATION_NAME = 'app'
AUTH_USER_MODEL = 'core.User'

CSRF_TRUSTED_ORIGINS = ["https://*.pythontr.com"]
