#!/usr/bin/env python
"""Test authentication integration - unauthenticated requests should return 401."""

import tempfile
from pathlib import Path
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient
from fastapi import FastAPI

from app.database.session import create_database_engine, shutdown_database, initialize_database, get_db_session
from app.services.auth_service import create_user
from app.routes import invoices, clients, products, payments, activities, business_profile, notifications, dashboard, auth, health


def test_auth_integration():
    """Test that unauthenticated requests return 401 and authenticated work."""
    temp_dir = tempfile.TemporaryDirectory()
    db_path = Path(temp_dir.name) / 'test_auth.db'
    engine = create_database_engine(f'sqlite:///{db_path.as_posix()}')
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

    initialize_database(engine)

    # Create admin user using the same session factory
    def get_test_db():
        session = session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    # Create admin user
    session = next(get_test_db())
    try:
        create_user(session, username='admin', password='SecurePass123!', is_admin=True)
        session.commit()
    finally:
        session.close()

    # Create app with all routes - override the database dependency
    app = FastAPI()
    app.include_router(invoices.router)
    app.include_router(clients.router)
    app.include_router(products.router)
    app.include_router(payments.router)
    app.include_router(activities.router)
    app.include_router(business_profile.router)
    app.include_router(notifications.router)
    app.include_router(dashboard.router)
    app.include_router(auth.router)
    app.include_router(health.router)

    # Override the database dependency to use our test session factory
    app.dependency_overrides[get_db_session] = get_test_db

    client = TestClient(app)

    # Test unauthenticated access to protected endpoints
    endpoints = [
        '/api/invoices',
        '/api/clients',
        '/api/products',
        '/api/payments',
        '/api/activities',
        '/api/business-profile',
        '/api/notifications',
        '/api/dashboard/summary',
    ]

    print('Testing unauthenticated access (should return 401):')
    all_pass = True
    for endpoint in endpoints:
        response = client.get(endpoint)
        status_ok = response.status_code == 401
        status_str = "PASS" if status_ok else "FAIL"
        if not status_ok:
            all_pass = False
        print('  GET {}: {} - {}'.format(endpoint, response.status_code, status_str))

    # Test health endpoint (should NOT require auth)
    response = client.get('/api/health')
    status_ok = response.status_code == 200
    status_str = "PASS" if status_ok else "FAIL"
    if not status_ok:
        all_pass = False
    print('  GET /api/health: {} - {}'.format(response.status_code, status_str))

    # Test auth endpoints (should NOT require auth)
    response = client.post('/api/auth/login', json={'username': 'admin', 'password': 'SecurePass123!', 'remember': True})
    status_ok = response.status_code == 200
    status_str = "PASS" if status_ok else "FAIL"
    if not status_ok:
        all_pass = False
    print('  POST /api/auth/login: {} - {}'.format(response.status_code, status_str))

    if response.status_code == 200:
        token = response.json()['token']
        headers = {'Authorization': 'Bearer ' + token}

        # Test authenticated access
        for endpoint in endpoints:
            response = client.get(endpoint, headers=headers)
            status_ok = response.status_code == 200
            status_str = "PASS" if status_ok else "FAIL"
            if not status_ok:
                all_pass = False
            print('  GET {} (auth): {} - {}'.format(endpoint, response.status_code, status_str))

    print('')
    if all_pass:
        print('=== ALL AUTH INTEGRATION TESTS PASSED ===')
    else:
        print('=== SOME TESTS FAILED ===')

    shutdown_database(engine)
    temp_dir.cleanup()
    return all_pass


if __name__ == '__main__':
    import sys
    success = test_auth_integration()
    sys.exit(0 if success else 1)