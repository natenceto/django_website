import socket
import threading

def forward(src_conn, dst_ip, dst_port):
    dst_conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        dst_conn.connect((dst_ip, dst_port))
    except Exception as e:
        print(f"Cannot connect to destination {dst_ip}:{dst_port}: {e}")
        src_conn.close()
        return

    def copy_data(from_conn, to_conn):
        try:
            while True:
                data = from_conn.recv(4096)
                if not data:
                    break
                to_conn.sendall(data)
        except Exception:
            pass
        finally:
            from_conn.close()
            to_conn.close()

    threading.Thread(target=copy_data, args=(src_conn, dst_conn), daemon=True).start()
    threading.Thread(target=copy_data, args=(dst_conn, src_conn), daemon=True).start()

def main():
    print("THIS SCRIPT MUST BE RUN ON THE HOST PC (192.168.88.243), NOT INSIDE THE VM!")
    print("It will listen on port 8000 and forward traffic to the VM.")
    
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    
    try:
        server.bind(('0.0.0.0', 8000))
    except Exception as e:
        print(f"Could not bind to port 8000: {e}")
        return
        
    server.listen(5)
    print("Listening on 0.0.0.0:8000... (Press Ctrl+C to stop)")
    
    try:
        while True:
            client, addr = server.accept()
            print(f"Received connection from EV Charger: {addr}")
            forward(client, '192.168.122.246', 8000)
    except KeyboardInterrupt:
        print("\nStopping forwarder.")
    finally:
        server.close()

if __name__ == '__main__':
    main()
