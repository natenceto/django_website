#!/usr/bin/env python3
"""
Проверка на различни портове за ABB Terra станция
"""
import socket
import time

def check_port_range(host, start_port, end_port):
    """Проверява диапазон от портове"""
    print(f"Проверка на {host} портове {start_port}-{end_port}:")
    open_ports = []
    
    for port in range(start_port, end_port + 1):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            result = sock.connect_ex((host, port))
            sock.close()
            
            if result == 0:
                open_ports.append(port)
                print(f"  ✓ Порт {port} е отворен")
            else:
                if port % 100 == 0:  # Показва прогрес на всеки 100 порта
                    print(f"  ... проверен порт {port}")
                    
        except Exception as e:
            pass
    
    return open_ports

def main():
    print("=" * 60)
    print("ПРОВЕРКА НА ПОРТОВЕ ЗА ABB TERRA СТАНЦИЯ")
    print("=" * 60)
    
    # Основни портове за проверка
    common_modbus_ports = [502, 503, 802, 803, 5020, 5021, 5022]
    
    print("\n1. Проверка на стандартни Modbus портове:")
    print("-" * 40)
    
    for port in common_modbus_ports:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            result = sock.connect_ex(('192.168.88.251', port))
            sock.close()
            
            if result == 0:
                print(f"  ✓ Порт {port} (192.168.88.251) - ОТВОРЕН")
            else:
                print(f"  ✗ Порт {port} (192.168.88.251) - затворен")
                
        except Exception as e:
            print(f"  ✗ Порт {port} (192.168.88.251) - грешка: {e}")
    
    print("\n2. Бърза проверка на често срещани портове (1-1024):")
    print("-" * 40)
    
    # Проверка на важни портове
    important_ports = [21, 22, 23, 25, 53, 80, 110, 143, 443, 993, 995, 8080, 8443]
    
    for port in important_ports:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            result = sock.connect_ex(('192.168.88.251', port))
            sock.close()
            
            if result == 0:
                print(f"  ✓ Порт {port} - ОТВОРЕН")
                
        except:
            pass
    
    print("\n3. Проверка на Modbus порт 502 с по-дълъг timeout:")
    print("-" * 40)
    
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(10)  # По-дълъг timeout
        print("Опит за свързване към 192.168.88.251:502 (timeout: 10s)...")
        result = sock.connect_ex(('192.168.88.251', 502))
        sock.close()
        
        if result == 0:
            print("  ✓ Успешно свързване!")
        else:
            print(f"  ✗ Неуспешно свързване (код: {result})")
            
    except Exception as e:
        print(f"  ✗ Грешка: {e}")
    
    print("\n" + "=" * 60)
    print("ИНСТРУКЦИИ ЗА КОНФИГУРАЦИЯ НА ABB TERRA:")
    print("=" * 60)
    print("1. Отидете в Local Controller -> Modbus TCP/IP")
    print("2. Въведете следните настройки:")
    print("   Address: 192.168.88.251")
    print("   Mask: 255.255.255.0") 
    print("   Default Gateway: 192.168.88.1")
    print("   Server Port: 502")
    print("3. Запазете и рестартирайте станцията")
    print("4. Изчакайте 2-3 минути след рестарт")
    print("5. Тествайте отново с: python test_fixed_modbus.py")
    print("=" * 60)

if __name__ == "__main__":
    main()
