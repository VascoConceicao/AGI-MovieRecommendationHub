from flask import Flask
from g15_common.docs.api_docs import init_api_docs


def test_parent_swagger_is_served():
    app = Flask(__name__)
    init_api_docs(app)
    response = app.test_client().get('/docs/swagger.html')
    assert response.status_code == 200
    assert b'SwaggerUIBundle' in response.data
