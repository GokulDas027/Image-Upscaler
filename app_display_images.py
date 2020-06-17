import os
from uuid import uuid4
import glob
from flask import Flask, request, render_template, send_from_directory
import image_upscaler

app = Flask(__name__)
# app = Flask(__name__, static_folder="images")


APP_ROOT = os.path.dirname(os.path.abspath(__file__))
@app.route("/")
def index():
    for file in glob.glob("./input/*"):
        os.remove(file)
    return render_template("index.html")

@app.route("/upload", methods=["POST"])
def upload():
    target = os.path.join(APP_ROOT, 'input')
    # target = os.path.join(APP_ROOT, 'static/')
    print(target)
    if not os.path.isdir(target):
            os.mkdir(target)
    else:
        print("Couldn't create upload directory: {}".format(target))
    print(request.files.getlist("file"))
    for upload in request.files.getlist("file"):
        print(upload)
        print("{} is the file name".format(upload.filename))
        filename = upload.filename
        destination = "/".join([target, filename])
        print ("Accept incoming file:", filename)
        print ("Save it to:", destination)
        upload.save(destination)
    gan = request.form.get('mycheckbox')
    scale = request.form.get('mycheckbox1')
    resl = request.form.get('mycheckbox2')
    print(gan)
    print(scale)
    print(resl)
    # return send_from_directory("images", filename, as_attachment=True)
    return render_template("display.html", image_name=filename)

@app.route('/upload/<filename>')
def send_image(filename):
    flask_return = image_upscaler.main(scale=scale, gan=True, keep_res=True)
    return send_from_directory("input", filename=flask_return[0])




if __name__ == "__main__":
    app.run(port=5000, debug=True)
