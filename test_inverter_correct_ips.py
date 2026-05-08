#!/usr/bin/env python3
"""
Тест на инвертори с коригирани IP адреси
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import logging
logging.basicConfig(level=logging.INFO)

# Директен импорт без Django
sys.path.append('/home/natenceto/Main/Work/Projects/RENEW/github/django_website')

def test_inverter_connectivity():
    """Тест на връзка към инверторите с правилните IP адреси"""
    print("=" * 60)
    print("ТЕСТ НА INVERTER ВРЪЗКИ - КОРИГИРАНИ IP АДРЕСИ")
    print("=" * 60)
    
    # Конфигурация с правилните IP адреси
    inverters = [
        {
            'ip': '192.168.88.253',
            'sn': 2409109016,
            'description': 'Master инвертор'
        },
        {
            'ip': '192.168.88.254', 
            'sn': 2409109073,
            'description': 'Slave инвертор'
        }
    ]
    
    for inverter in inverters:
        print(f"\nТестване на {inverter['description']}")
        print(f"IP: {inverter['ip']}, SN: {inverter['sn']}")
        
        # Тест на Solarman порт 8899
        try:
            import socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(3)
            result = sock.connect_ex((inverter['ip'], 8899))
            sock.close()
            
            if result == 0:
                print(f"  ✓ Порт 8899 (Solarman) достъпен")
                
                # Тест с DeyeLocalClient ако е възможно
                try:
                    from renew_website.apps.api.deye.local_client import DeyeLocalClient
                    client = DeyeLocalClient(
                        ip_address=inverter['ip'],
                        serial_number=inverter['sn']
                    )
                    
                    data = client.fetch_all_metrics()
                    if data:
                        print(f"  ✓ Успешно четене на данни:")
                        for key, value in list(data.items())[:3]:
                            print(f"    {key}: {value}")
                    else:
                        print(f"  ✗ Неуспешно четене на данни")
                        
                except Exception as e:
                    print(f"  ✗ Грешка при DeyeLocalClient: {e}")
                    
            else:
                print(f"  ✗ Порт 8899 (Solarman) недостъпен (код: {result})")
                
        except Exception as e:
            print(f"  ✗ Грешка при тестване: {e}")

if __name__ == "__main__":
    test_inverter_connectivity()
