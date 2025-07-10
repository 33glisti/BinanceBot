from sqlalchemy import create_engine, Column, Integer, String, Float, BigInteger
from sqlalchemy.orm import declarative_base, sessionmaker
import time

Base = declarative_base()

class Order(Base):
    __tablename__ = 'orders'
    order_id = Column(Integer, primary_key=True)
    symbol = Column(String)
    side = Column(String)
    price = Column(Float)
    volume = Column(Float)
    status = Column(String)
    created_at = Column(BigInteger)

engine = create_engine('sqlite:///orders.db')
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)

def save_or_update_orders(order_list):
    with Session() as session:
        for o in order_list:
            order = session.query(Order).filter_by(order_id=o['orderId']).first()
            if order:
                order.status = 'OPEN'
            else:
                order = Order(
                    order_id=o['orderId'],
                    symbol=o['symbol'],
                    side=o['side'],
                    price=float(o['price']),
                    volume=float(o['origQty']),
                    status='OPEN',
                    created_at=int(time.time())
                )
                session.add(order)
        session.commit()

def get_filled_orders(active_symbols):
    with Session() as session:
        return session.query(Order).filter(Order.status == 'OPEN', Order.symbol.in_(active_symbols)).all()

def mark_order_filled(order_id):
    with Session() as session:
        order = session.query(Order).filter_by(order_id=order_id).first()
        if order:
            order.status = 'FILLED'
            session.commit()
