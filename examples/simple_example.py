class UserValidator:
    """Validates user data"""

    def __init__(self):
        self.min_age = 18
        self.max_age = 120

    def validate_age(self, age: int) -> bool:
        """
        Validate if age is within acceptable range.

        Args:
            age: User's age

        Returns:
            True if age is valid, False otherwise
        """
        if age < self.min_age:
            return False
        if age > self.max_age:
            return False
        return True

    def validate_email(self, email: str) -> bool:
        """
        Validate if email format is correct.

        Args:
            email: Email address to validate

        Returns:
            True if email is valid, False otherwise
        """
        if not email:
            return False
        if "@" not in email:
            return False
        if "." not in email:
            return False

        parts = email.split("@")
        if len(parts) != 2:
            return False

        local, domain = parts
        if not local or not domain:
            return False

        return True

    def validate_username(self, username: str) -> bool:
        """
        Validate if username meets requirements.

        Args:
            username: Username to validate

        Returns:
            True if username is valid, False otherwise
        """
        if not username:
            return False
        if len(username) < 3:
            return False
        if len(username) > 20:
            return False
        if not username.isalnum():
            return False
        return True
