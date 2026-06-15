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

    # --- PROSES ELEMINASI/FILTER DATA SEBELUM PERHITUNGAN SAW ---
    mobil_lolos_filter = []
    for m in semua_mobil:
        # A. Filter Berdasarkan Merk
        if pref['merk'] != 'Semua' and m['merk'] != pref['merk']:
            continue
            
        # B. Filter Berdasarkan Jenis Bahan Bakar
        if pref['bahan_bakar'] != 'Semua' and m['bahan_bakar'] != pref['bahan_bakar']:
            continue
            
        # C. Filter Berdasarkan Kompleksitas Transmisi (Otomatis mencakup AT, CVT, DCT)
        if pref['transmisi'] != 'Semua':
            if pref['transmisi'] == 'Otomatis':
                if m['transmisi'] not in ['AT', 'CVT', 'DCT']:
                    continue
            elif pref['transmisi'] == 'Manual':
                if m['transmisi'] != 'MT':
                    continue
                    
        # D. Filter Berdasarkan Jangkauan Nilai Harga OTR
        if not (pref['harga_min'] <= m['harga'] <= pref['harga_max']):
            continue
            
        # Jika lolos seluruh seleksi filter, masukkan ke list komputasi SAW
        mobil_lolos_filter.append(m)

    # --- JIKA FILTER MENGHASILKAN 0 MOBIL, gunakan (FALLBACK) ---
    if not mobil_lolos_filter:
        # Cari nilai max/min global untuk normalisasi (dari semua mobil)
        min_harga_global = min(m['harga'] for m in semua_mobil) if semua_mobil else 0
        max_mesin_global = max(m['kapasitas_mesin'] for m in semua_mobil) if semua_mobil else 1
        max_penumpang_global = max(m['kapasitas_penumpang'] for m in semua_mobil) if semua_mobil else 1
        max_tangki_global = max(m['kapasitas_tangki'] for m in semua_mobil) if semua_mobil else 1
        
        # Vektor preferensi ideal: semua nilai normalisasi = 1 (harga semurah mungkin, benefit maksimal)
        ideal = [1, 1, 1, 1]
        w = [bobot['harga'], bobot['kapasitas_mesin'], bobot['kapasitas_penumpang'], bobot['kapasitas_tangki']]
        
        def weighted_euclidean_distance(mobil):
            # Normalisasi COST: harga (semakin kecil r_harga semakin besar? kita balik agar ideal=1)
            # Rumus: r_harga = min_harga_global / harga, kemudian batasi maksimal 1
            if mobil['harga'] > 0:
                r_harga = min_harga_global / mobil['harga']
            else:
                r_harga = 0
            r_harga = min(1.0, r_harga)
            
            # Normalisasi BENEFIT: nilai / max
            r_mesin = mobil['kapasitas_mesin'] / max_mesin_global if max_mesin_global > 0 else 0
            r_penumpang = mobil['kapasitas_penumpang'] / max_penumpang_global if max_penumpang_global > 0 else 0
            r_tangki = mobil['kapasitas_tangki'] / max_tangki_global if max_tangki_global > 0 else 0
            
            vektor_mobil = [r_harga, r_mesin, r_penumpang, r_tangki]
            
            # Hitung jarak berbobot
            jarak = 0
            for i in range(4):
                jarak += w[i] * ((ideal[i] - vektor_mobil[i]) ** 2)
            return jarak ** 0.5
        
        # Hitung jarak untuk setiap mobil dan urutkan
        for m in semua_mobil:
            m['jarak'] = weighted_euclidean_distance(m)
        
        hasil_ranking = sorted(semua_mobil, key=lambda x: x['jarak'])
        hasil_ranking = hasil_ranking[:20]  # batasi 20 teratas
        
        # Tampilkan dengan fallback = True
        return render_template('hasil_saw.html', ranking=hasil_ranking, bobot=bobot, empty_result=True, fallback=True)
    
    # --- JIKA ADA HASIL FILTER, PROSES SAW NORMAL ---
    min_harga = min(m['harga'] for m in mobil_lolos_filter)
    max_mesin = max(m['kapasitas_mesin'] for m in mobil_lolos_filter)
    max_penumpang = max(m['kapasitas_penumpang'] for m in mobil_lolos_filter)
    max_tangki = max(m['kapasitas_tangki'] for m in mobil_lolos_filter)

    hasil_ranking = []
    for m in mobil_lolos_filter:
        r_harga = min_harga / m['harga'] if m['harga'] > 0 else 0
        r_mesin = m['kapasitas_mesin'] / max_mesin if max_mesin > 0 else 0
        r_penumpang = m['kapasitas_penumpang'] / max_penumpang if max_penumpang > 0 else 0
        r_tangki = m['kapasitas_tangki'] / max_tangki if max_tangki > 0 else 0

        v_nilai = (r_harga * bobot['harga']) + \
                  (r_mesin * bobot['kapasitas_mesin']) + \
                  (r_penumpang * bobot['kapasitas_penumpang']) + \
                  (r_tangki * bobot['kapasitas_tangki'])
        
        m['nilai_v'] = round(v_nilai, 4)
        hasil_ranking.append(m)

    hasil_ranking = sorted(hasil_ranking, key=lambda x: x['nilai_v'], reverse=True)
    return render_template('hasil_saw.html', ranking=hasil_ranking, bobot=bobot, empty_result=False, fallback=False)