import os
import uuid  
from flask import Flask, render_template, request, redirect, url_for, session, flash, send_from_directory
import mysql.connector
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
import secrets
from urllib.parse import urlparse

app = Flask(__name__)
app.secret_key = 'kunci_rahasia_spk_mpv' # WAJIB ADA untuk session

def generate_csrf_token():
    """Buat atau ambil token CSRF dari session"""
    if 'csrf_token' not in session:
        session['csrf_token'] = secrets.token_hex(16)
    return session['csrf_token']

def verify_csrf_token(token):
    """Verifikasi apakah token cocok dengan session"""
    return token and token == session.get('csrf_token')

@app.route('/favicon.ico')
def favicon():
    return send_from_directory(
        os.path.join(app.root_path, 'static'),
        'favicon.png',                          
        mimetype='image/png'                    
    )

# ==========================================
# --- KONFIGURASI UPLOAD GAMBAR ---
# ==========================================
UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Membuat folder static/uploads secara otomatis jika belum ada
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Fungsi helper untuk validasi format file gambar
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


# --- KONEKSI DATABASE ---
def get_db_connection():
    # Coba ambil URL database dari environment variable (Railway)
    database_url = os.environ.get('DATABASE_URL') or os.environ.get('MYSQL_URL')
    
    if database_url:
        from urllib.parse import urlparse
        url = urlparse(database_url)
        connection = mysql.connector.connect(
            host=url.hostname,
            user=url.username,
            password=url.password,
            database=url.path[1:],  # hapus leading '/'
            port=url.port or 3306
        )
    else:
        # Konfigurasi lokal (XAMPP)
        connection = mysql.connector.connect(
            host='localhost',
            user='root',
            password='',
            database='db_spk'
        )
    return connection

# ==========================================
# --- ROUTE PUBLIC (FRONTEND) ---
# ==========================================

@app.route('/')
def home():
    # Cek kelengkapan data filter dan bobot kriteria di session user
    has_session = 'filter_preferences' in session and 'bobot_ahp' in session
    
    # Ambil jumlah total mobil langsung dari database
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT COUNT(*) AS total FROM tb_mobil")
    result = cursor.fetchone()
    
    # Jika database kosong, set default ke 0
    total_mobil = result['total'] if result else 0
    conn.close()
    
    # Kirim variabel has_session dan total_mobil ke template index.html
    return render_template('index.html', has_session=has_session, total_mobil=total_mobil)

@app.route('/data-mobil')
def page_data_mobil():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Ganti ORDER BY kode (tidak ada) dengan kolom yang masih ada, misal id_mobil atau merk
    cursor.execute('SELECT * FROM tb_mobil ORDER BY id_mobil ASC')
    data_mobil_db = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template('data_mobil.html', mobil=data_mobil_db)

# ==========================================
# --- ROUTE FILTER AWAL ---
# ==========================================

@app.route('/input-filter', methods=['GET', 'POST'])
def input_filter():
    if request.method == 'POST':
        # 1. Ambil data preferensi wajib dari form filter
        merk = request.form.get('merk', 'Semua')
        transmisi = request.form.get('transmisi', 'Semua')
        bahan_bakar = request.form.get('bahan_bakar', 'Semua')
        
        # Amankan data konversi angka manual jangkauan harga
        try:
            harga_min = float(request.form.get('harga_min') or 0)
        except ValueError:
            harga_min = 0.0
            
        try:
            harga_max = float(request.form.get('harga_max') or 9999999999)
        except ValueError:
            harga_max = 9999999999.0

        # 2. Simpan preferensi filter kriteria ke dalam session
        session['filter_preferences'] = {
            'merk': merk,
            'transmisi': transmisi,
            'bahan_bakar': bahan_bakar,
            'harga_min': harga_min,
            'harga_max': harga_max
        }
        
        # Alihkan langkah berikutnya menuju pengisian Kuesioner AHP
        return redirect(url_for('input_ahp'))

    # Jika metodenya GET, tampilkan halaman form filter beserta data session yang tersimpan (jika ada)
    saved_filter = session.get('filter_preferences', {
        'merk': 'Semua',
        'transmisi': 'Semua',
        'bahan_bakar': 'Semua',
        'harga_min': 0,
        'harga_max': 9999999999
    })
    
    return render_template('filter.html', saved_filter=saved_filter)

# ==========================================
# --- ROUTE AHP & SAW (USER SPK PROCESS) ---
# ==========================================

@app.route('/input-ahp')
def input_ahp():
    # Proteksi: Pastikan user sudah melewati halaman filter terlebih dahulu
    if 'filter_preferences' not in session:
        flash('Silakan tentukan filter kriteria mutlak Anda terlebih dahulu!', 'warning')
        return redirect(url_for('input_filter'))
    
    # AMBIL DATA SLIDER LAMA DARI SESSION (Default kosong jika belum pernah mengisi)
    saved_inputs = session.get('ahp_inputs', {})
    
    # Kirim saved_inputs ke template
    return render_template('ahp_input.html', saved_inputs=saved_inputs)

@app.route('/proses-ahp', methods=['POST'])
def proses_ahp():
    def konversi_skala(val):
        val = int(val)
        if val < 0:
            return float(abs(val) + 1)  # Geser ke Kiri (Kriteria pertama dominan)
        elif val > 0:
            return float(1 / (val + 1)) # Geser ke Kanan (Kriteria kedua dominan)
        else:
            return 1.0                  # Tengah-tengah (Sama penting)

    if request.method == 'POST':
        # --- REVISI: SIMPAN STATE RAW INPUT SLIDER KE SESSION ---
        session['ahp_inputs'] = {
            'c1_c2': request.form.get('c1_c2', '0'),
            'c1_c3': request.form.get('c1_c3', '0'),
            'c1_c4': request.form.get('c1_c4', '0'),
            'c2_c3': request.form.get('c2_c3', '0'),
            'c2_c4': request.form.get('c2_c4', '0'),
            'c3_c4': request.form.get('c3_c4', '0')
        }

        # Menangkap 6 parameter berpasangan dari form input (Matriks n = 4)
        try:
            k_values = {
                'c1_c2': konversi_skala(request.form['c1_c2']),
                'c1_c3': konversi_skala(request.form['c1_c3']),
                'c1_c4': konversi_skala(request.form['c1_c4']),
                'c2_c3': konversi_skala(request.form['c2_c3']),
                'c2_c4': konversi_skala(request.form['c2_c4']),
                'c3_c4': konversi_skala(request.form['c3_c4'])
            }
        except KeyError:
            flash('Mohon lengkapi seluruh baris kuesioner kriteria!', 'danger')
            return redirect(url_for('input_ahp'))

        # Menyusun struktur matriks perbandingan berpasangan AHP
        matriks = [
            [1.0, k_values['c1_c2'], k_values['c1_c3'], k_values['c1_c4']],
            [1/k_values['c1_c2'], 1.0, k_values['c2_c3'], k_values['c2_c4']],
            [1/k_values['c1_c3'], 1/k_values['c2_c3'], 1.0, k_values['c3_c4']],
            [1/k_values['c1_c4'], 1/k_values['c2_c4'], 1/k_values['c3_c4'], 1.0]
        ]

        # Hitung jumlah total nilai per kolom matriks
        jumlah_kolom = [sum(matriks[baris][kolom] for baris in range(4)) for kolom in range(4)]

        # Proses normalisasi matriks dan dapatkan nilai bobot prioritas kriteria (Eigenvector)
        bobot_prioritas = []
        for baris in range(4):
            jumlah_normalisasi_baris = 0
            for kolom in range(4):
                nilai_normal = matriks[baris][kolom] / jumlah_kolom[kolom]
                jumlah_normalisasi_baris += nilai_normal
            bobot_prioritas.append(round(jumlah_normalisasi_baris / 4, 4))

        # Simpan nilai bobot hasil perhitungan AHP ke dalam session
        session['bobot_ahp'] = {
            'harga': bobot_prioritas[0],
            'kapasitas_mesin': bobot_prioritas[1],
            'kapasitas_penumpang': bobot_prioritas[2],
            'kapasitas_tangki': bobot_prioritas[3]
        }

        return redirect(url_for('hasil_saw'))

@app.route('/hasil-rekomendasi')
def hasil_saw():
    # Proteksi berlapis session data
    if 'filter_preferences' not in session:
        return redirect(url_for('input_filter'))
    if 'bobot_ahp' not in session:
        flash('Silakan isi kuesioner preferensi terlebih dahulu!', 'warning')
        return redirect(url_for('input_ahp'))
    
    pref = session['filter_preferences']
    bobot = session['bobot_ahp']
    
    # Ambil seluruh data pool dari database
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM tb_mobil")
    semua_mobil = cursor.fetchall()
    conn.close()

    # -------------------------------------------------------------------------
    # FUNGSI BANTU: MENERAPKAN FILTER DENGAN TINGKAT PELONGGARAN TERTENTU
    # level 0 = semua filter (original)
    # level 1 = abaikan merk
    # level 2 = abaikan merk + transmisi
    # level 3 = abaikan merk + transmisi + bahan bakar
    # level 4 = hanya filter harga (abaikan merk, transmisi, bahan bakar)
    # level 5 = tanpa filter apapun (semua mobil)
    # -------------------------------------------------------------------------
    def apply_filter_by_level(mobil_list, pref, level):
        hasil = []
        for m in mobil_list:
            # Filter harga: hanya diterapkan jika level < 5
            if level < 5 and not (pref['harga_min'] <= m['harga'] <= pref['harga_max']):
                continue
            
            if level >= 1:
                # abaikan filter merk
                pass
            else:
                if pref['merk'] != 'Semua' and m['merk'] != pref['merk']:
                    continue
            
            if level >= 2:
                # abaikan filter transmisi
                pass
            else:
                if pref['transmisi'] != 'Semua':
                    if pref['transmisi'] == 'Otomatis':
                        if m['transmisi'] not in ['AT', 'CVT', 'DCT']:
                            continue
                    elif pref['transmisi'] == 'Manual':
                        if m['transmisi'] != 'MT':
                            continue
            
            if level >= 3:
                # abaikan filter bahan bakar
                pass
            else:
                if pref['bahan_bakar'] != 'Semua' and m['bahan_bakar'] != pref['bahan_bakar']:
                    continue
            
            hasil.append(m)
        
        return hasil

    # -------------------------------------------------------------------------
    # FUNGSI BANTU: MENGHITUNG SAW PADA SUATU HIMPUNAN MOBIL
    # -------------------------------------------------------------------------
    def hitung_saw(daftar_mobil):
        if not daftar_mobil:
            return []
        
        min_harga = min(m['harga'] for m in daftar_mobil)
        max_mesin = max(m['kapasitas_mesin'] for m in daftar_mobil)
        max_penumpang = max(m['kapasitas_penumpang'] for m in daftar_mobil)
        max_tangki = max(m['kapasitas_tangki'] for m in daftar_mobil)
        
        # Hindari pembagian dengan nol
        max_mesin = max_mesin if max_mesin > 0 else 1
        max_penumpang = max_penumpang if max_penumpang > 0 else 1
        max_tangki = max_tangki if max_tangki > 0 else 1
        
        hasil = []
        for m in daftar_mobil:
            # Normalisasi cost (harga)
            r_harga = min_harga / m['harga'] if m['harga'] > 0 else 0
            # Normalisasi benefit
            r_mesin = m['kapasitas_mesin'] / max_mesin
            r_penumpang = m['kapasitas_penumpang'] / max_penumpang
            r_tangki = m['kapasitas_tangki'] / max_tangki
            
            # Nilai preferensi V (SAW)
            v_nilai = (r_harga * bobot['harga']) + \
                      (r_mesin * bobot['kapasitas_mesin']) + \
                      (r_penumpang * bobot['kapasitas_penumpang']) + \
                      (r_tangki * bobot['kapasitas_tangki'])
            
            m_copy = m.copy()
            m_copy['nilai_v'] = round(v_nilai, 4)
            hasil.append(m_copy)
        
        hasil.sort(key=lambda x: x['nilai_v'], reverse=True)
        return hasil

    # -------------------------------------------------------------------------
    # PROSES UTAMA: COBA FILTER BERTINGKAT
    # -------------------------------------------------------------------------
    # Pertama coba level 0 (semua filter)
    mobil_lolos = apply_filter_by_level(semua_mobil, pref, level=0)
    fallback_level = 0
    used_fallback = False
    
    # Jika tidak ada, coba level 1 sampai 5
    if not mobil_lolos:
        used_fallback = True
        for level in range(1, 6):
            mobil_lolos = apply_filter_by_level(semua_mobil, pref, level)
            if mobil_lolos:
                fallback_level = level
                break
    
    # Jika setelah level 5 tetap tidak ada (seharusnya ada karena level 5 tanpa filter)
    if not mobil_lolos:
        mobil_lolos = semua_mobil
        fallback_level = 5
        used_fallback = True
    
    # Hitung SAW pada himpunan mobil yang berhasil dikumpulkan
    hasil_ranking = hitung_saw(mobil_lolos)
    
    # Batasi maksimal 20 rekomendasi untuk tampilan
    hasil_ranking = hasil_ranking[:20]
    
    # -------------------------------------------------------------------------
    # TENTUKAN FILTER YANG DIABAIKAN BERDASARKAN FALLBACK_LEVEL
    # -------------------------------------------------------------------------
    ignored_list = []
    if used_fallback and fallback_level >= 1:
        ignored_list.append("Merk")
    if used_fallback and fallback_level >= 2:
        ignored_list.append("Transmisi")
    if used_fallback and fallback_level >= 3:
        ignored_list.append("Bahan Bakar")
    if used_fallback and fallback_level == 5:
        ignored_list.append("Harga")
    
    # Buat string deskripsi filter yang diabaikan
    if ignored_list:
        if len(ignored_list) == 1:
            ignored_filters_str = ignored_list[0]
        else:
            ignored_filters_str = ", ".join(ignored_list[:-1]) + " dan " + ignored_list[-1]
    else:
        ignored_filters_str = ""
    
    # Kirim ke template
    return render_template('hasil_saw.html', 
                           ranking=hasil_ranking, 
                           bobot=bobot, 
                           empty_result=used_fallback,   # fallback terjadi, tampilkan pesan peringatan
                           fallback=used_fallback,
                           fallback_level=fallback_level,
                           ignored_filters=ignored_filters_str,
                           original_pref=pref)  # kirim preferensi asli untuk info filter yang diminta

# ==========================================
# --- ROUTE AUTHENTICATION (LOGIN/LOGOUT) ---
# ==========================================

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM tb_users WHERE username = %s", (username,))
        user = cursor.fetchone()
        cursor.close()
        conn.close()

        # Cek user ada dan password hash cocok
        if user and check_password_hash(user['password'], password):
            session['loggedin'] = True
            session['id_user'] = user['id_user']  # konsisten dengan session di fungsi lain
            session['username'] = user['username']
            session['nama'] = user['nama_lengkap']
            session['role'] = user['role']
            
            return redirect(url_for('admin_dashboard'))
        else:
            flash('Username atau Password salah!', 'danger')
    
    return render_template('auth/login.html')

@app.route('/logout')
def logout():
    # Hapus semua data session user
    session.pop('loggedin', None)
    session.pop('id_user', None)   # konsisten dengan session di login
    session.pop('username', None)
    session.pop('nama', None)
    session.pop('role', None)
    
    # Hapus semua flash messages yang belum terbaca (termasuk "Login berhasil")
    session.pop('_flashes', None)
    
    return redirect(url_for('login'))

# @app.route('/admin/dashboard')
# def admin_dashboard():
#     if 'loggedin' not in session:
#         return redirect(url_for('login'))
    
#     # Ambil jumlah total data mobil secara dinamis dari database
#     conn = get_db_connection()
#     cursor = conn.cursor()
#     cursor.execute("SELECT COUNT(*) FROM tb_mobil")
#     total_mobil = cursor.fetchone()[0]
#     cursor.close()
#     conn.close()
    
#     # Lempar variabel total_mobil ke dalam template dashboard admin
#     return render_template('admin/dashboard.html', total_mobil=total_mobil)

@app.route('/admin/dashboard')
def admin_dashboard():
    if 'loggedin' not in session:
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM tb_mobil")
    total_mobil = cursor.fetchone()[0]
    
    # Jika superadmin, ambil juga total users
    total_users = None
    if session.get('role') == 'superadmin':
        cursor.execute("SELECT COUNT(*) FROM tb_users")
        total_users = cursor.fetchone()[0]
    
    cursor.close()
    conn.close()
    
    return render_template('admin/dashboard.html', 
                          total_mobil=total_mobil, 
                          total_users=total_users)

# ==========================================
# --- MANAGEMENTS CRUD MOBIL (ADMIN ONLY) ---
# ==========================================

@app.route('/admin/users')
def admin_users():
    # Proteksi Lapis Kedua (Backend): Cek apakah user sudah login dan merupakan superadmin
    if not session.get('loggedin') or session.get('role') != 'superadmin':
        flash('Anda tidak memiliki hak akses untuk membuka halaman Manajemen Users!', 'danger')
        return redirect(url_for('admin_dashboard'))
        
    # Jika lolos proteksi, ambil data seluruh user dari database
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT id_user, username, nama_lengkap, role FROM tb_users ORDER BY id_user DESC")
    users = cursor.fetchall()
    cursor.close()
    conn.close()
    
    # Kirim data users ke dalam template HTML
    return render_template('admin/users_index.html', users=users)

# =======================================================
# 1. ROUTE TAMBAH DATA USER (dengan template users_form.html)
# =======================================================
@app.route('/admin/users/tambah', methods=['GET', 'POST'])
def admin_users_tambah():
    # Proteksi Backend: Hanya superadmin yang sudah login
    if not session.get('loggedin') or session.get('role') != 'superadmin':
        flash('Anda tidak memiliki hak akses ke halaman ini!', 'danger')
        return redirect(url_for('admin_dashboard'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        nama_lengkap = request.form.get('nama_lengkap', '').strip()
        password = request.form.get('password', '').strip()
        role = request.form.get('role', '').strip()

        # Validasi 1: Semua field wajib diisi (khusus tambah, password wajib)
        if not username or not nama_lengkap or not password or not role:
            flash('Semua field (termasuk password) wajib diisi!', 'danger')
            # Kirim kembali data yang sudah diisi (kecuali password) agar tidak hilang
            return render_template('admin/users_form.html', 
                                   form_data={'username': username, 'nama_lengkap': nama_lengkap, 'role': role})

        # Validasi 2: Password minimal 8 karakter
        if len(password) < 8:
            flash('Password harus minimal 8 karakter!', 'danger')
            return render_template('admin/users_form.html',
                                   form_data={'username': username, 'nama_lengkap': nama_lengkap, 'role': role})

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Validasi 3: Cek username duplikat
        cursor.execute("SELECT id_user FROM tb_users WHERE username = %s", (username,))
        if cursor.fetchone():
            cursor.close()
            conn.close()
            flash('Username sudah terdaftar, silakan gunakan username lain!', 'danger')
            return render_template('admin/users_form.html',
                                   form_data={'username': username, 'nama_lengkap': nama_lengkap, 'role': role})

        # Hash password
        hashed_password = generate_password_hash(password)

        try:
            cursor.execute(
                "INSERT INTO tb_users (username, nama_lengkap, password, role) VALUES (%s, %s, %s, %s)",
                (username, nama_lengkap, hashed_password, role)
            )
            conn.commit()
            flash('Data user baru berhasil ditambahkan!', 'success')
            return redirect(url_for('admin_users'))
        except Exception as e:
            flash(f'Terjadi kesalahan saat menyimpan data: {str(e)}', 'danger')
        finally:
            cursor.close()
            conn.close()

    # Method GET: tampilkan form kosong (mode tambah)
    return render_template('admin/users_form.html')


# =======================================================
# 2. ROUTE EDIT DATA USER (dengan template users_form.html)
# =======================================================
@app.route('/admin/users/edit/<int:id>', methods=['GET', 'POST'])
def admin_users_edit(id):
    # Proteksi Backend: Hanya superadmin yang sudah login
    if not session.get('loggedin') or session.get('role') != 'superadmin':
        flash('Anda tidak memiliki hak akses ke halaman ini!', 'danger')
        return redirect(url_for('admin_dashboard'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Ambil data user yang akan diedit
    cursor.execute("SELECT * FROM tb_users WHERE id_user = %s", (id,))
    user = cursor.fetchone()

    if not user:
        cursor.close()
        conn.close()
        flash('Data user tidak ditemukan!', 'danger')
        return redirect(url_for('admin_users'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        nama_lengkap = request.form.get('nama_lengkap', '').strip()
        password = request.form.get('password', '').strip()  # opsional
        role = request.form.get('role', '').strip()

        # Validasi 1: Field utama tidak boleh kosong
        if not username or not nama_lengkap or not role:
            flash('Username, Nama Lengkap, dan Role wajib diisi!', 'danger')
            cursor.close()
            conn.close()
            return render_template('admin/users_form.html', user=user)

        # Validasi 2: Cek duplikasi username (kecuali dirinya sendiri)
        cursor.execute("SELECT id_user FROM tb_users WHERE username = %s AND id_user != %s", (username, id))
        if cursor.fetchone():
            flash('Username tersebut sudah digunakan oleh user lain!', 'danger')
            cursor.close()
            conn.close()
            return render_template('admin/users_form.html', user=user)

        # Proses update
        try:
            if password:
                # Jika password diisi, harus minimal 8 karakter
                if len(password) < 8:
                    flash('Password minimal 8 karakter!', 'danger')
                    cursor.close()
                    conn.close()
                    return render_template('admin/users_form.html', user=user)
                hashed_password = generate_password_hash(password)
                cursor.execute(
                    "UPDATE tb_users SET username = %s, nama_lengkap = %s, password = %s, role = %s WHERE id_user = %s",
                    (username, nama_lengkap, hashed_password, role, id)
                )
            else:
                # Password kosong: tidak ubah password
                cursor.execute(
                    "UPDATE tb_users SET username = %s, nama_lengkap = %s, role = %s WHERE id_user = %s",
                    (username, nama_lengkap, role, id)
                )
            conn.commit()
            flash('Data user berhasil diperbarui!', 'success')
            return redirect(url_for('admin_users'))
        except Exception as e:
            flash(f'Terjadi kesalahan saat memperbarui data: {str(e)}', 'danger')
        finally:
            cursor.close()
            conn.close()

    cursor.close()
    conn.close()
    # Method GET: tampilkan form dengan data user yang ada
    return render_template('admin/users_form.html', user=user)

# =======================================================
# 3. ROUTE HAPUS DATA USER
# =======================================================
@app.route('/admin/users/hapus/<int:id>', methods=['POST'])
def admin_users_hapus(id):
    # Proteksi Backend: Hanya untuk superadmin yang sudah login
    if not session.get('loggedin') or session.get('role') != 'superadmin':
        flash('Anda tidak memiliki hak akses untuk menghapus user!', 'danger')
        return redirect(url_for('admin_dashboard'))
    
    # Cek apakah user yang akan dihapus adalah dirinya sendiri (superadmin yang sedang login)
    if session.get('id_user') == id:
        flash('Anda tidak dapat menghapus akun sendiri yang sedang aktif!', 'danger')
        return redirect(url_for('admin_users'))
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Cek apakah user dengan id tersebut ada
    cursor.execute("SELECT id_user, username FROM tb_users WHERE id_user = %s", (id,))
    user = cursor.fetchone()
    
    if not user:
        cursor.close()
        conn.close()
        flash('Data user tidak ditemukan!', 'danger')
        return redirect(url_for('admin_users'))
    
    try:
        # Eksekusi penghapusan
        cursor.execute("DELETE FROM tb_users WHERE id_user = %s", (id,))
        conn.commit()
        flash(f'User "{user["username"]}" berhasil dihapus!', 'success')
    except Exception as e:
        flash(f'Terjadi kesalahan saat menghapus data: {str(e)}', 'danger')
    finally:
        cursor.close()
        conn.close()
    
    return redirect(url_for('admin_users'))

# 1. READ: Tampilkan Semua Data Mobil
@app.route('/admin/mobil')
def admin_mobil():
    if 'loggedin' not in session: return redirect(url_for('login'))
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Diubah karena kolom 'kode' sudah dihapus.
    # Sekarang diurutkan berdasarkan Merk, Model, dan Varian agar data otomatis terkelompok dengan rapi.
    cursor.execute("""
        SELECT * FROM tb_mobil 
        ORDER BY merk ASC, model ASC, varian ASC
    """)
    
    mobil = cursor.fetchall()
    conn.close()
    
    return render_template('admin/mobil_index.html', mobil=mobil)

# 2. CREATE: Tambah Data Baru dengan Fitur Upload File fisik
@app.route('/admin/mobil/tambah', methods=['GET', 'POST'])
@app.route('/admin/mobil/tambah', methods=['GET', 'POST'])
def admin_mobil_tambah():
    if 'loggedin' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        # --- VALIDASI CSRF TOKEN (CEGAH DOUBLE SUBMIT) ---
        csrf_token = request.form.get('csrf_token')
        if not verify_csrf_token(csrf_token):
            flash('Token keamanan tidak valid. Silakan submit ulang form.', 'danger')
            return redirect(url_for('admin_mobil_tambah'))

        # Ambil input dan bersihkan spasi di awal/akhir teks
        merk = request.form['merk'].strip()
        model = request.form['model'].strip()
        varian = request.form['varian'].strip()
        transmisi = request.form['transmisi'].strip()
        bahan_bakar = request.form['bahan_bakar'].strip()
        harga = request.form['harga'].strip()
        kapasitas_mesin = request.form['kapasitas_mesin'].strip()
        kapasitas_penumpang = request.form['kapasitas_penumpang'].strip()
        kapasitas_tangki = request.form['kapasitas_tangki'].strip()

        # Siapkan struktur data fallback untuk dikembalikan ke form jika validasi gagal
        form_fallback = {
            'merk': merk, 'model': model, 'varian': varian,
            'transmisi': transmisi, 'bahan_bakar': bahan_bakar, 'gambar': '',
            'harga': harga, 'kapasitas_mesin': kapasitas_mesin,
            'kapasitas_penumpang': kapasitas_penumpang, 'kapasitas_tangki': kapasitas_tangki
        }

        # --- JALUR VALIDASI STRICT BACKEND ---
        try:
            # A. Validasi Field Text (Mencegah kolom kosong & Data Too Long MySQL)
            if not merk or len(merk) > 50:
                raise ValueError("Merk tidak boleh kosong dan maksimal 50 karakter.")
            if not model or len(model) > 50:
                raise ValueError("Model tidak boleh kosong dan maksimal 50 karakter.")
            if not varian or len(varian) > 100:
                raise ValueError("Varian tidak boleh kosong dan maksimal 100 karakter.")

            # B. Validasi Kesesuaian ENUM Database
            if transmisi not in ['AT', 'MT', 'CVT', 'DCT']:
                raise ValueError("Pilihan transmisi tidak valid.")
            if bahan_bakar not in ['Bensin', 'Diesel']:
                raise ValueError("Pilihan bahan bakar tidak valid.")

            # C. Validasi Angka dan Proteksi Overflow (BIGINT / INT)
            if not harga.isdigit():
                raise ValueError("Harga harus berupa angka bulat positif.")
            harga_val = int(harga)
            if harga_val <= 0 or harga_val > 999999999999:  # Batas aman di bawah BIGINT max
                raise ValueError("Harga tidak logis atau melebihi batas (Maks 1 Triliun).")

            if not kapasitas_mesin.isdigit():
                raise ValueError("Kapasitas mesin harus berupa angka.")
            mesin_val = int(kapasitas_mesin)
            if mesin_val <= 0 or mesin_val > 20000:  # Batas aman INT(11) mesin mobil
                raise ValueError("Kapasitas mesin harus di antara 1 s.d 20.000 CC.")

            if not kapasitas_penumpang.isdigit():
                raise ValueError("Kapasitas penumpang harus berupa angka.")
            penumpang_val = int(kapasitas_penumpang)
            if penumpang_val <= 0 or penumpang_val > 100:
                raise ValueError("Kapasitas penumpang harus di antara 1 s.d 100 orang.")

            if not kapasitas_tangki.isdigit():
                raise ValueError("Kapasitas tangki harus berupa angka.")
            tangki_val = int(kapasitas_tangki)
            if tangki_val <= 0 or tangki_val > 2000:
                raise ValueError("Kapasitas tangki harus di antara 1 s.d 2.000 Liter.")

        except ValueError as e:
            flash(f"Gagal simpan! {str(e)}", 'danger')
            return render_template('admin/mobil_form.html', mobil=form_fallback)

        # Proses Upload Gambar
        gambar = ''
        if 'gambar' in request.files:
            file = request.files['gambar']
            if file and file.filename != '':
                if allowed_file(file.filename):
                    ext = file.filename.rsplit('.', 1)[1].lower()
                    filename = f"{uuid.uuid4().hex}.{ext}"
                    file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                    gambar = filename
                else:
                    flash('Format gambar salah! Gunakan format .png, .jpg, atau .jpeg', 'danger')
                    return render_template('admin/mobil_form.html', mobil=form_fallback)

        # Jika lolos validasi, masukkan nilai yang sudah bersih & aman ke DB
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO tb_mobil (merk, model, varian, transmisi, bahan_bakar, gambar, harga, kapasitas_mesin, kapasitas_penumpang, kapasitas_tangki) 
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (merk, model, varian, transmisi, bahan_bakar, gambar, harga_val, mesin_val, penumpang_val, tangki_val))

        conn.commit()
        conn.close()
        flash('Data mobil berhasil ditambahkan!', 'success')
        return redirect(url_for('admin_mobil'))

    # Method GET: generate token baru dan kirim ke template
    generate_csrf_token()  # pastikan token ada di session
    return render_template('admin/mobil_form.html', mobil=None, csrf_token=session['csrf_token'])


# 3. UPDATE: Edit Data dengan Otomatis Hapus Gambar Lama dari Server jika diganti
@app.route('/admin/mobil/edit/<int:id>', methods=['GET', 'POST'])
def admin_mobil_edit(id):
    if 'loggedin' not in session:
        return redirect(url_for('login'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Ambil data lama terlebih dahulu untuk keperluan fallback gambar
    cursor.execute("SELECT * FROM tb_mobil WHERE id_mobil = %s", (id,))
    data = cursor.fetchone()
    if not data:
        conn.close()
        flash('Data mobil tidak ditemukan!', 'danger')
        return redirect(url_for('admin_mobil'))

    if request.method == 'POST':
        # --- VALIDASI CSRF TOKEN (CEGAH DOUBLE SUBMIT) ---
        csrf_token = request.form.get('csrf_token')
        if not verify_csrf_token(csrf_token):
            flash('Token keamanan tidak valid. Silakan submit ulang form.', 'danger')
            return redirect(url_for('admin_mobil_edit', id=id))

        # Ambil input dan bersihkan spasi di awal/akhir teks
        merk = request.form['merk'].strip()
        model = request.form['model'].strip()
        varian = request.form['varian'].strip()
        transmisi = request.form['transmisi'].strip()
        bahan_bakar = request.form['bahan_bakar'].strip()
        harga = request.form['harga'].strip()
        kapasitas_mesin = request.form['kapasitas_mesin'].strip()
        kapasitas_penumpang = request.form['kapasitas_penumpang'].strip()
        kapasitas_tangki = request.form['kapasitas_tangki'].strip()

        # Siapkan struktur data fallback dengan mengamankan id dan gambar lama
        form_fallback = {
            'id_mobil': id, 'merk': merk, 'model': model, 'varian': varian,
            'transmisi': transmisi, 'bahan_bakar': bahan_bakar, 'gambar': data['gambar'] if data else '',
            'harga': harga, 'kapasitas_mesin': kapasitas_mesin,
            'kapasitas_penumpang': kapasitas_penumpang, 'kapasitas_tangki': kapasitas_tangki
        }

        # --- JALUR VALIDASI STRICT BACKEND ---
        try:
            # A. Validasi Field Text
            if not merk or len(merk) > 50:
                raise ValueError("Merk tidak boleh kosong dan maksimal 50 karakter.")
            if not model or len(model) > 50:
                raise ValueError("Model tidak boleh kosong dan maksimal 50 karakter.")
            if not varian or len(varian) > 100:
                raise ValueError("Varian tidak boleh kosong dan maksimal 100 karakter.")

            # B. Validasi Kesesuaian ENUM Database
            if transmisi not in ['AT', 'MT', 'CVT', 'DCT']:
                raise ValueError("Pilihan transmisi tidak valid.")
            if bahan_bakar not in ['Bensin', 'Diesel']:
                raise ValueError("Pilihan bahan bakar tidak valid.")

            # C. Validasi Angka dan Proteksi Overflow
            if not harga.isdigit():
                raise ValueError("Harga harus berupa angka bulat positif.")
            harga_val = int(harga)
            if harga_val <= 0 or harga_val > 999999999999:
                raise ValueError("Harga tidak logis atau melebihi batas (Maks 1 Triliun).")

            if not kapasitas_mesin.isdigit():
                raise ValueError("Kapasitas mesin harus berupa angka.")
            mesin_val = int(kapasitas_mesin)
            if mesin_val <= 0 or mesin_val > 20000:
                raise ValueError("Kapasitas mesin harus di antara 1 s.d 20.000 CC.")

            if not kapasitas_penumpang.isdigit():
                raise ValueError("Kapasitas penumpang harus berupa angka.")
            penumpang_val = int(kapasitas_penumpang)
            if penumpang_val <= 0 or penumpang_val > 100:
                raise ValueError("Kapasitas penumpang harus di antara 1 s.d 100 orang.")

            if not kapasitas_tangki.isdigit():
                raise ValueError("Kapasitas tangki harus berupa angka.")
            tangki_val = int(kapasitas_tangki)
            if tangki_val <= 0 or tangki_val > 2000:
                raise ValueError("Kapasitas tangki harus di antara 1 s.d 2.000 Liter.")

        except ValueError as e:
            conn.close()
            flash(f"Gagal memperbarui! {str(e)}", 'danger')
            return render_template('admin/mobil_form.html', mobil=form_fallback, csrf_token=session['csrf_token'])

        # Secara default, pakai nama file gambar yang sudah ada di database
        gambar = data['gambar'] if data else ''

        # Jika admin mengunggah file baru, gantikan gambar lama
        if 'gambar' in request.files:
            file = request.files['gambar']
            if file and file.filename != '':
                if allowed_file(file.filename):
                    if data and data['gambar']:
                        old_path = os.path.join(app.config['UPLOAD_FOLDER'], data['gambar'])
                        if os.path.exists(old_path):
                            os.remove(old_path)

                    ext = file.filename.rsplit('.', 1)[1].lower()
                    filename = f"{uuid.uuid4().hex}.{ext}"
                    file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                    gambar = filename
                else:
                    conn.close()
                    flash('Format gambar salah! Gunakan format .png, .jpg, atau .jpeg', 'danger')
                    return render_template('admin/mobil_form.html', mobil=form_fallback, csrf_token=session['csrf_token'])

        cursor.execute("""
            UPDATE tb_mobil 
            SET merk=%s, model=%s, varian=%s, transmisi=%s, bahan_bakar=%s, gambar=%s, harga=%s, kapasitas_mesin=%s, kapasitas_penumpang=%s, kapasitas_tangki=%s
            WHERE id_mobil=%s
        """, (merk, model, varian, transmisi, bahan_bakar, gambar, harga_val, mesin_val, penumpang_val, tangki_val, id))

        conn.commit()
        conn.close()
        flash('Data mobil berhasil diperbarui!', 'success')
        return redirect(url_for('admin_mobil'))

    conn.close()
    # Method GET: kirim token ke template
    generate_csrf_token()
    return render_template('admin/mobil_form.html', mobil=data, csrf_token=session['csrf_token'])

# 4. DELETE: Hapus Data Sekaligus File Gambar Fisiknya
@app.route('/admin/mobil/hapus/<int:id>')
def admin_mobil_hapus(id):
    if 'loggedin' not in session: return redirect(url_for('login'))
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Dapatkan nama file gambar lama sebelum baris data di-delete
    cursor.execute("SELECT gambar FROM tb_mobil WHERE id_mobil = %s", (id,))
    data = cursor.fetchone()
    
    # Hapus file gambar secara fisik dari server jika file tersebut ada
    if data and data['gambar']:
        old_path = os.path.join(app.config['UPLOAD_FOLDER'], data['gambar'])
        if os.path.exists(old_path):
            os.remove(old_path)
            
    cursor.execute("DELETE FROM tb_mobil WHERE id_mobil = %s", (id,))
    conn.commit()
    conn.close()
    
    flash('Data mobil dan file gambar berhasil dihapus!', 'danger')
    return redirect(url_for('admin_mobil'))


# if __name__ == '__main__':
#     app.run(debug=True)
if __name__ == '__main__':
    # Mengambil port otomatis dari Railway, jika tidak ada (di lokal) pakai port 5000
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)