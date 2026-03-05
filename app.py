from flask import Flask, render_template, request, redirect, url_for, session, flash
import mysql.connector

app = Flask(__name__)
app.secret_key = 'kunci_rahasia_spk_mpv' # WAJIB ADA untuk session

# --- KONEKSI DATABASE ---
def get_db_connection():
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
    return render_template('index.html')

@app.route('/data-mobil')
def page_data_mobil():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Query ambil semua data
    cursor.execute('SELECT * FROM tb_mobil')
    data_mobil_db = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template('data_mobil.html', mobil=data_mobil_db)

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
        cursor.execute("SELECT * FROM tb_users WHERE username = %s AND password = %s", (username, password))
        user = cursor.fetchone()
        cursor.close()
        conn.close()

        if user:
            session['loggedin'] = True
            session['id'] = user['id_user']
            session['username'] = user['username']
            session['nama'] = user['nama_lengkap']
            return redirect(url_for('admin_dashboard'))
        else:
            flash('Username atau Password salah!', 'danger')
    
    return render_template('auth/login.html')

@app.route('/logout')
def logout():
    session.pop('loggedin', None)
    session.pop('id', None)
    session.pop('username', None)
    session.pop('nama', None)
    return redirect(url_for('login'))

# ==========================================
# --- ROUTE ADMIN PANEL ---
# ==========================================

@app.route('/admin/dashboard')
def admin_dashboard():

    if 'loggedin' not in session:
        return redirect(url_for('login'))

    return render_template('admin/dashboard.html')

# 1. READ: Tampilkan Semua Data
@app.route('/admin/mobil')
def admin_mobil():
    if 'loggedin' not in session: return redirect(url_for('login'))
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM tb_mobil ORDER BY kode ASC")
    mobil = cursor.fetchall()
    conn.close()
    
    return render_template('admin/mobil_index.html', mobil=mobil)

# 2. CREATE: Tambah Data Baru (UPDATE LOGIC)
@app.route('/admin/mobil/tambah', methods=['GET', 'POST'])
def admin_mobil_tambah():
    if 'loggedin' not in session: return redirect(url_for('login'))

    if request.method == 'POST':
        kode = request.form['kode']
        nama = request.form['nama_mobil']
        harga = request.form['harga']
        kursi = request.form['kursi']
        bbm = request.form['bbm']
        tenaga = request.form['tenaga']
        # --- UPDATE BARU: Ambil data Safety ---
        fitur_safety = request.form['fitur_safety'] 

        conn = get_db_connection()
        cursor = conn.cursor()
        # --- UPDATE BARU: Masukkan ke Query SQL ---
        cursor.execute("""
            INSERT INTO tb_mobil (kode, nama_mobil, harga, kursi, bbm, tenaga, fitur_safety) 
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (kode, nama, harga, kursi, bbm, tenaga, fitur_safety))
        
        conn.commit()
        conn.close()
        flash('Data mobil berhasil ditambahkan!', 'success')
        return redirect(url_for('admin_mobil'))

    return render_template('admin/mobil_form.html', mobil=None)

# 3. UPDATE: Edit Data (UPDATE LOGIC)
@app.route('/admin/mobil/edit/<int:id>', methods=['GET', 'POST'])
def admin_mobil_edit(id):
    if 'loggedin' not in session: return redirect(url_for('login'))
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    if request.method == 'POST':
        kode = request.form['kode']
        nama = request.form['nama_mobil']
        harga = request.form['harga']
        kursi = request.form['kursi']
        bbm = request.form['bbm']
        tenaga = request.form['tenaga']
        # --- UPDATE BARU ---
        fitur_safety = request.form['fitur_safety']

        # --- UPDATE BARU: Query Update ---
        cursor.execute("""
            UPDATE tb_mobil 
            SET kode=%s, nama_mobil=%s, harga=%s, kursi=%s, bbm=%s, tenaga=%s, fitur_safety=%s
            WHERE id_mobil=%s
        """, (kode, nama, harga, kursi, bbm, tenaga, fitur_safety, id))
        
        conn.commit()
        conn.close()
        flash('Data mobil berhasil diperbarui!', 'success')
        return redirect(url_for('admin_mobil'))
    
    cursor.execute("SELECT * FROM tb_mobil WHERE id_mobil = %s", (id,))
    data = cursor.fetchone()
    conn.close()
    
    return render_template('admin/mobil_form.html', mobil=data)

# 4. DELETE: Hapus Data
@app.route('/admin/mobil/hapus/<int:id>')
def admin_mobil_hapus(id):
    if 'loggedin' not in session: return redirect(url_for('login'))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM tb_mobil WHERE id_mobil = %s", (id,))
    conn.commit()
    conn.close()
    
    flash('Data mobil berhasil dihapus!', 'danger')
    return redirect(url_for('admin_mobil'))

# ==========================================
# --- ROUTE AHP & SAW (USER END) ---
# ==========================================

@app.route('/input-ahp')
def input_ahp():
    return render_template('ahp_input.html')

@app.route('/proses-ahp', methods=['POST'])
def proses_ahp():
    # Fungsi pembantu untuk mengkonversi nilai slider (-8 s/d 8) ke skala AHP (1-9 atau 1/9-1)
    def konversi_skala(val):
        val = int(val)
        if val < 0:
            # Mengarah ke Kiri (Kriteria A lebih penting)
            return abs(val) + 1
        elif val > 0:
            # Mengarah ke Kanan (Kriteria B lebih penting)
            return 1 / (val + 1)
        else:
            # Tengah-tengah (Sama penting)
            return 1.0

    if request.method == 'POST':
        # 1. Tangkap 10 input dari form
        k_values = {
            'c1_c2': konversi_skala(request.form['c1_c2']),
            'c1_c3': konversi_skala(request.form['c1_c3']),
            'c1_c4': konversi_skala(request.form['c1_c4']),
            'c1_c5': konversi_skala(request.form['c1_c5']),
            'c2_c3': konversi_skala(request.form['c2_c3']),
            'c2_c4': konversi_skala(request.form['c2_c4']),
            'c2_c5': konversi_skala(request.form['c2_c5']),
            'c3_c4': konversi_skala(request.form['c3_c4']),
            'c3_c5': konversi_skala(request.form['c3_c5']),
            'c4_c5': konversi_skala(request.form['c4_c5'])
        }

        # 2. Susun Matriks Perbandingan Berpasangan 5x5
        # Index: 0=Harga, 1=BBM, 2=Tenaga, 3=Kursi, 4=Safety
        matriks = [
            [1.0, k_values['c1_c2'], k_values['c1_c3'], k_values['c1_c4'], k_values['c1_c5']],
            [1/k_values['c1_c2'], 1.0, k_values['c2_c3'], k_values['c2_c4'], k_values['c2_c5']],
            [1/k_values['c1_c3'], 1/k_values['c2_c3'], 1.0, k_values['c3_c4'], k_values['c3_c5']],
            [1/k_values['c1_c4'], 1/k_values['c2_c4'], 1/k_values['c3_c4'], 1.0, k_values['c4_c5']],
            [1/k_values['c1_c5'], 1/k_values['c2_c5'], 1/k_values['c3_c5'], 1/k_values['c4_c5'], 1.0]
        ]

        # 3. Hitung Jumlah per Kolom
        jumlah_kolom = [sum(matriks[baris][kolom] for baris in range(5)) for kolom in range(5)]

        # 4. Normalisasi Matriks (dibagi jumlah kolom) & Hitung Bobot (Rata-rata Baris)
        bobot_prioritas = []
        for baris in range(5):
            jumlah_normalisasi_baris = 0
            for kolom in range(5):
                nilai_normal = matriks[baris][kolom] / jumlah_kolom[kolom]
                jumlah_normalisasi_baris += nilai_normal
            # Rata-rata dari 5 kolom
            bobot_prioritas.append(round(jumlah_normalisasi_baris / 5, 4))

        # 5. Simpan Bobot (W) ke dalam Session! (Sesuai Diagram 3.19)
        session['bobot_ahp'] = {
            'harga': bobot_prioritas[0],
            'bbm': bobot_prioritas[1],
            'tenaga': bobot_prioritas[2],
            'kursi': bobot_prioritas[3],
            'safety': bobot_prioritas[4]
        }

        # Redirect ke tahap SAW
        return redirect(url_for('hasil_saw'))

# Route sementara
# @app.route('/hasil-rekomendasi')
# def hasil_saw():
#     if 'bobot_ahp' not in session:
#         return redirect(url_for('input_ahp'))
    
#     return f"<h1>AHP Sukses!</h1><p>Bobot tersimpan di Session: {session['bobot_ahp']}</p>"

@app.route('/hasil-rekomendasi')
def hasil_saw():
    # 1. Validasi Session (Sesuai Sequence Diagram 3.20)
    if 'bobot_ahp' not in session:
        flash('Silakan isi kuesioner preferensi terlebih dahulu!', 'warning')
        return redirect(url_for('input_ahp'))
    
    bobot = session['bobot_ahp']
    
    # 2. Ambil Data Mobil dari Database
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM tb_mobil")
    mobil_list = cursor.fetchall()
    conn.close()

    if not mobil_list:
        return "<h1>Error: Data mobil kosong di database!</h1>"

    # 3. Cari Nilai Max dan Min untuk Normalisasi
    min_harga = min(m['harga'] for m in mobil_list)
    max_bbm = max(m['bbm'] for m in mobil_list)
    max_tenaga = max(m['tenaga'] for m in mobil_list)
    max_kursi = max(m['kursi'] for m in mobil_list)
    max_safety = max(m['fitur_safety'] for m in mobil_list)

    hasil_ranking = []
    
    # 4. Proses Normalisasi (R) dan Hitung Nilai Preferensi (V)
    for m in mobil_list:
        # Normalisasi (R)
        r_harga = min_harga / m['harga'] if m['harga'] > 0 else 0  # COST
        r_bbm = m['bbm'] / max_bbm if max_bbm > 0 else 0          # BENEFIT
        r_tenaga = m['tenaga'] / max_tenaga if max_tenaga > 0 else 0 # BENEFIT
        r_kursi = m['kursi'] / max_kursi if max_kursi > 0 else 0     # BENEFIT
        r_safety = m['fitur_safety'] / max_safety if max_safety > 0 else 0 # BENEFIT

        # Hitung Nilai V = (R * W)
        v_nilai = (r_harga * bobot['harga']) + \
                  (r_bbm * bobot['bbm']) + \
                  (r_tenaga * bobot['tenaga']) + \
                  (r_kursi * bobot['kursi']) + \
                  (r_safety * bobot['safety'])
        
        # Simpan nilai V ke dalam dictionary mobil
        m['nilai_v'] = round(v_nilai, 4)
        hasil_ranking.append(m)

    # 5. Sorting (Urutkan dari nilai V tertinggi ke terendah)
    hasil_ranking = sorted(hasil_ranking, key=lambda x: x['nilai_v'], reverse=True)

    # Kirim data ke tampilan HTML
    return render_template('hasil_saw.html', ranking=hasil_ranking, bobot=bobot)
    
if __name__ == '__main__':
    app.run(debug=True)