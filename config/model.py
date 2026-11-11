
from django.db import models


class Product(models.Model):
    name = models.CharField(max_length=200)
    description = models.TextField()
    price = models.DecimalField(max_digits=10, decimal_places=2)
    image_url = models.URLField(blank=True)
    stock = models.PositiveIntegerField(default=0)
    category = models.CharField(max_length=100, default="General")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name
    
