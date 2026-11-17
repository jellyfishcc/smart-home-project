"""SQLite identity and person binding; no application/model startup."""
import hashlib
import json
from pathlib import Path
from sqlalchemy.engine import make_url


def gallery_scope(database_uri):
    url = make_url(database_uri)
    if url.get_backend_name() != 'sqlite' or not url.database or url.database == ':memory:':
        raise ValueError('Face gallery requires an explicit SQLite file identity')
    if not Path(url.database).is_absolute():
        raise ValueError('Use an absolute SQLite path to avoid Flask instance-path ambiguity')
    database = Path(url.database).resolve()
    return str(database), database.with_name('face_embeddings.' + database.name + '.pkl')


def person_token(person):
    fields = [int(person.id), str(person.employee_id), str(person.created_at)]
    return hashlib.sha256(json.dumps(fields, ensure_ascii=False).encode()).hexdigest()


def person_lookup(app, identity):
    def lookup(person_id):
        if gallery_scope(app.config['SQLALCHEMY_DATABASE_URI'])[0] != identity:
            return None  # Config switch requires constructing a fresh scoped service.
        from models import AuthorizedPerson
        with app.app_context():
            person = AuthorizedPerson.query.get(int(person_id))
            if person is None:
                return None
            _, path = gallery_scope(app.config['SQLALCHEMY_DATABASE_URI'])
            return {'token': person_token(person),
                    'registered': bool(person.face_image_path and Path(person.face_image_path).is_file()
                                       and person.face_encoding_path == str(path))}
    return lookup
