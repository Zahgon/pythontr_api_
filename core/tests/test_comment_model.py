from app.testing import TestCase
from app.testing import get_user_model

from core.models import Category, Article, Comment, content_type_id_for


def test_user(email='test@hotmail.com', password='123qwe'):
    return get_user_model().objects.create_user(email, password)


def test_category(name='Php Programlama', short_name='php'):
    return Category.objects.create(
        user=test_user(),
        name=name,
        short_name=short_name,
    )


class ModelTests(TestCase):

    def test_comment_str(self):
        category = test_category()
        user = test_user('test123@hotmail.com')
        article = Article.objects.create(
            user=user,
            title='Sqrt fonksiyonu  pythontr.com',
            description='bla bla....',
        )
        article.categories.append(category)

        comment = Comment.objects.create(
            content_type_id=content_type_id_for('article'),
            object_id=article.id,
            content='Bla bla',
            email='huseyin@pythontr.com',
        )

        self.assertEqual(str(comment), comment.content)

    def test_reply_comment(self):
        category = test_category()
        user = test_user('test321@hotmail.com')
        article = Article.objects.create(
            user=user,
            title='Sqrt fonksiyonu  pythontr.com',
            description='bla bla....',
        )
        article.categories.append(category)

        comment = Comment.objects.create(
            content_type_id=content_type_id_for('article'),
            object_id=article.id,
            content='It is wonderful content',
            email='huseyin@pythontr.com',
        )

        comment_reply = Comment.objects.create(
            content_type_id=content_type_id_for('comment'),
            object_id=comment.id,
            content='I am not thinking.....',
            email='huseyin@pythontr.com',
        )

        self.assertGreaterEqual(comment_reply.content_object.id, 0)
