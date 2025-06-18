import zipfile

dataset_zip = "dataset.zip"

if zipfile.is_zipfile(dataset_zip):
    with zipfile.ZipFile(dataset_zip, 'r') as zip_ref:
        zip_ref.extractall("dataset")
    print("✅ Dataset uspešno razpakiran.")
else:
    print("❌ Napaka: To ni veljavna ZIP datoteka.")
