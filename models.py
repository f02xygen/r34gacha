from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, BigInteger
from sqlalchemy.orm import declarative_base, relationship
import datetime

Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    telegram_id = Column(BigInteger, unique=True, index=True, nullable=False)
    username = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    
    collection = relationship("UserCollection", back_populates="user")

class Character(Base):
    __tablename__ = "characters"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    tag_name = Column(String, unique=True, index=True, nullable=False)
    post_count = Column(Integer, default=0)
    best_image_url = Column(String, nullable=True)
    
    collections = relationship("UserCollection", back_populates="character")

class UserCollection(Base):
    __tablename__ = "user_collections"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    character_id = Column(Integer, ForeignKey("characters.id", ondelete="CASCADE"), nullable=False)
    amount = Column(Integer, default=1)
    obtained_at = Column(DateTime, default=datetime.datetime.utcnow)
    
    user = relationship("User", back_populates="collection")
    character = relationship("Character", back_populates="collections")
