from frontend import db, app

def recreate_database():
    print("Dropping all tables...")
    with app.app_context():
        db.drop_all()
        print("All tables dropped.")

    print("Creating all tables...")
    with app.app_context():
        db.create_all()
        print("All tables created.")

if __name__ == "__main__":
    recreate_database()
