class DatabaseRouter:
    """
    A router to control all database operations on models in the
    auth, contenttypes, sessions, and admin applications.
    """
    
    # Apps that must reside in the 'default' (SQLite) database
    auth_apps = {'auth', 'contenttypes', 'sessions', 'admin', 'accounts'}
    
    # Apps that must reside in the 'postgres_db' (Business) database
    business_apps = {'charging_stations', 'energy', 'weather', 'api', 'deye'}

    def db_for_read(self, model, **hints):
        """
        Attempts to read auth/contenttypes/sessions models from 'default'.
        Reads business models from 'postgres_db'.
        """
        if model._meta.app_label in self.auth_apps:
            return 'default'
        if model._meta.app_label in self.business_apps:
            return 'postgres_db'
        return None

    def db_for_write(self, model, **hints):
        """
        Attempts to write auth/contenttypes/sessions models to 'default'.
        Writes business models to 'postgres_db'.
        """
        if model._meta.app_label in self.auth_apps:
            return 'default'
        if model._meta.app_label in self.business_apps:
            return 'postgres_db'
        return None

    def allow_relation(self, obj1, obj2, **hints):
        """
        Allow relations if a model in the auth_apps is involved?
        No, we strictly forbid cross-database relations.
        """
        # If both are in the same set of apps, allow
        if (
            obj1._meta.app_label in self.auth_apps and 
            obj2._meta.app_label in self.auth_apps
        ):
            return True
            
        if (
            obj1._meta.app_label in self.business_apps and 
            obj2._meta.app_label in self.business_apps
        ):
            return True

        # If we are mixing apps, deny relation (return None or False)
        # However, to be safe and explicit:
        if (
            obj1._meta.app_label in self.auth_apps and 
            obj2._meta.app_label in self.business_apps
        ):
            return False
            
        if (
            obj1._meta.app_label in self.business_apps and 
            obj2._meta.app_label in self.auth_apps
        ):
            return False

        return None

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        """
        Make sure the auth and contenttypes apps only appear in the
        'default' database.
        """
        if app_label in self.auth_apps:
            return db == 'default'
        
        if app_label in self.business_apps:
            return db == 'postgres_db'
            
        return None
