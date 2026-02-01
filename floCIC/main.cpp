#include <cmath>
#include <vector>
#include <cstdint>
#include <iostream>
#include <cstdlib>
#include <string>
#include <stdexcept>
#include <algorithm>


#ifdef _WIN32
#include <io.h>
#include <fcntl.h>
#endif

struct BitPacker {
    std::vector<uint8_t>& B;
    uint8_t cur = 0;
    int used = 0;

    explicit BitPacker(std::vector<uint8_t>& b) : B(b) {}

    void putBits(uint32_t value, int bits) {
        for (int k = bits - 1; k >= 0; --k) {
            uint32_t bit = (value >> k) & 1u;
            cur |= static_cast<uint8_t>(bit << (7 - used));
            used++;
            if (used == 8) {
                B.push_back(cur);
                cur = 0;
                used = 0;
            }
        }
    }

    void flush() {
        if (used != 0) {
            B.push_back(cur);
            cur = 0;
            used = 0;
        }
    }
};

struct Header {
    uint16_t height;
    int32_t  c0;
    int32_t  cLast;
    uint32_t n;
};


struct BitReaderMem {
    const uint8_t* data;
    size_t size;
    size_t pos = 0;

    uint8_t buffer = 0;
    int bitPos = 8;

    BitReaderMem(const uint8_t* d, size_t s) : data(d), size(s) {}

    uint8_t readU8() {
        if (pos >= size) throw std::runtime_error("Unexpected EOF");
        return data[pos++];
    }

    uint32_t readBits(int bits) {
        uint32_t value = 0;
        for (int i = 0; i < bits; ++i) {
            if (bitPos == 8) {
                buffer = readU8();
                bitPos = 0;
            }
            value = (value << 1) | ((buffer >> (7 - bitPos)) & 1u);
            bitPos++;
        }
        return value;
    }
};

static uint16_t readU16BE(BitReaderMem& br) {
    uint16_t hi = br.readU8();
    uint16_t lo = br.readU8();
    return (uint16_t)((hi << 8) | lo);
}

static uint32_t readU32BE(BitReaderMem& br) {
    uint32_t b0 = br.readU8();
    uint32_t b1 = br.readU8();
    uint32_t b2 = br.readU8();
    uint32_t b3 = br.readU8();
    return (b0 << 24) | (b1 << 16) | (b2 << 8) | b3;
}

static int32_t readI32BE(BitReaderMem& br) {
    return (int32_t)readU32BE(br);
}

static Header readHeader(BitReaderMem& br) {
    Header h{};
    h.height = readU16BE(br);
    h.c0     = readI32BE(br);
    h.cLast  = readI32BE(br);
    h.n      = readU32BE(br);
    return h;
}


static bool readExactStdin(std::vector<uint8_t>& buf, size_t n) {
    buf.resize(n);
    std::cin.read(reinterpret_cast<char*>(buf.data()), static_cast<std::streamsize>(n));
    return std::cin.gcount() == static_cast<std::streamsize>(n);
}

static std::vector<uint8_t> readAllStdin() {
    std::vector<uint8_t> data;
    std::vector<char> buf(64 * 1024);
    while (true) {
        std::cin.read(buf.data(), (std::streamsize)buf.size());
        std::streamsize got = std::cin.gcount();
        if (got <= 0) break;
        data.insert(data.end(), buf.begin(), buf.begin() + got);
    }
    return data;
}




static std::vector<std::vector<int32_t>> bytesToImage2D(const std::vector<uint8_t>& gray, int width, int height) {
    std::vector<std::vector<int32_t>> img(height, std::vector<int32_t>(width, 0));
    for (int y = 0; y < height; ++y) {
        for (int x = 0; x < width; ++x) {
            img[y][x] = static_cast<int32_t>(gray[y * width + x]); // 0..255
        }
    }
    return img;
}

static void writeAllStdout(const std::vector<uint8_t>& bytes) {
    std::cout.write(reinterpret_cast<const char*>(bytes.data()),
                    static_cast<std::streamsize>(bytes.size()));
}





/* READING BMP FILES */
static uint32_t rowStrideBytes(int width, int bitsPerPixel) {
    uint32_t bytesPerRow = (uint32_t)((width * bitsPerPixel + 7) / 8);
    return (bytesPerRow + 3) & ~3u;
}




/* COMPRESSION */

std::vector<int32_t> predict(std::vector<std::vector<int32_t>>& image, int height, int width) {

    std::vector<int32_t> prediction;
    prediction.push_back(image[0][0]);

    for (int j = 0; j < width; j++) {
        for (int i = 0; i < height; i++) {
            if (i == 0 && j == 0) continue;

            int16_t pred;
            if (j == 0) {
                pred = image[i-1][0];
            } else if (i == 0) {
                pred = image[0][j-1];
            } else {

                int16_t a = image[i][j-1];
                int16_t b = image[i-1][j];
                int16_t c = image[i-1][j-1];

                if (c >= std::max(a, b))
                    pred = std::min(a, b);
                else if (c <= std::min(a, b))
                    pred = std::max(a, b);
                else
                    pred = (int16_t)(a+b-c);
            }
            prediction.push_back((int16_t)(pred - image[i][j]));
        }
    }

    return prediction;
}

void setHeader(std::vector<uint8_t>& vectB, int height, int32_t c0, int32_t c_last, int n) {
    vectB.push_back((height >> 8) & 0xFF);
    vectB.push_back(height & 0xFF);

    vectB.push_back((c0 >> 24) & 0xFF);
    vectB.push_back((c0 >> 16) & 0xFF);
    vectB.push_back((c0 >> 8)  & 0xFF);
    vectB.push_back(c0 & 0xFF);

    vectB.push_back((c_last >> 24) & 0xFF);
    vectB.push_back((c_last >> 16) & 0xFF);
    vectB.push_back((c_last >> 8)  & 0xFF);
    vectB.push_back(c_last & 0xFF);

    vectB.push_back((n >> 24) & 0xFF);
    vectB.push_back((n >> 16) & 0xFF);
    vectB.push_back((n >> 8)  & 0xFF);
    vectB.push_back(n & 0xFF);
}



static int ceilLog2(uint32_t x) {
    // returns ceil(log2(x)) for x >= 1
    if (x <= 1) return 0;
    int g = 0;
    uint32_t v = x - 1;
    while (v) { g++; v >>= 1; }
    return g;
}

static void Encode(BitPacker& bp, int g, uint32_t value) {
    // write exactly g bits (MSB-first)
    if (g <= 0) return;
    bp.putBits(value, g);
}

void IC(BitPacker& bp, const std::vector<int32_t>& vectC, int L, int H) {

    if(H-L > 1) {
        if (vectC[H] != vectC[L]) {
            int m = std::floor(0.5*(H+L));
            int32_t CL = static_cast<int32_t>(vectC[L]);
            int32_t CH = static_cast<int32_t>(vectC[H]);
            int32_t CM = static_cast<int32_t>(vectC[m]);

            uint32_t range = static_cast<uint32_t>(CH - CL + 1); // (cH - cL + 1)
            int g = ceilLog2(range);

            uint32_t delta = static_cast<uint32_t>(CM - CL);     // (cM - cL)

            Encode(bp, g, delta);

            if (L<m) {
                IC(bp, vectC, L, m);
            }

            if (m<H) {
                IC(bp, vectC, m, H);
            }
        }
    }

}

std::string extractBaseName(const std::string& path) {
    size_t slash = path.find_last_of("/\\");
    size_t start = (slash == std::string::npos) ? 0 : slash + 1;

    size_t dot = path.find_last_of('.');
    if (dot == std::string::npos || dot < start) {
        return path.substr(start);
    }
    return path.substr(start, dot - start);
}




static std::vector<uint8_t> compress_to_bytes(std::vector<std::vector<int32_t>>& image, int height, int width) {
    std::vector<int32_t> predVector = predict(image, height, width);
    std::vector<int32_t> vectN;
    std::vector<int32_t> vectC;
    std::vector<uint8_t> vectBin;

    int n = width * height;

    vectN.reserve(n);
    vectC.reserve(n);

    vectN.push_back(predVector[0]);
    for (int i = 1; i < n; i++) {
        if (predVector[i] >= 0) vectN.push_back(2 * predVector[i]);
        else vectN.push_back(2 * std::abs(predVector[i]) - 1);
    }

    vectC.push_back(vectN[0]);
    for (int i = 1; i < n; i++) vectC.push_back(vectC.back() + vectN[i]);

    setHeader(vectBin, height, vectC[0], vectC.back(), n);

    BitPacker bp(vectBin);
    IC(bp, vectC, 0, n - 1);
    bp.flush();

    return vectBin;
}


/* DECOMPRESSION */


std::vector<std::vector<int32_t>> predictInverse(std::vector<int32_t>& predVect,
                                                 int height,
                                                 int width)
{
    std::vector<std::vector<int32_t>> data(height,
                                           std::vector<int32_t>(width, 0));

    data[0][0] = predVect[0];

    for (int i = 0; i < height; i++) {
        for (int j = 0; j < width; j++) {

            if (i == 0 && j == 0) {
                continue;
            }
            else if (j == 0) {
                data[i][0] = data[i - 1][0]
                           - predVect[j * height + i];
            }
            else if (i == 0) {
                data[0][j] = data[0][j - 1]
                           - predVect[j * height + i];
            }
            else {
                int32_t a = data[i][j - 1];     // left
                int32_t b = data[i - 1][j];     // up
                int32_t c = data[i - 1][j - 1]; // up-left

                int32_t pred;
                if (c >= std::max(a, b))
                    pred = std::min(a, b);
                else if (c <= std::min(a, b))
                    pred = std::max(a, b);
                else
                    pred = a + b - c;

                data[i][j] = pred
                           - predVect[j * height + i];
            }
        }
    }

    return data;
}

static void IC_decode(BitReaderMem& br, std::vector<int32_t>& C, int L, int H) {
    if (H - L <= 1) return;

    int m = (L + H) / 2;

    if (C[H] == C[L]) {
        C[m] = C[L];
        if (L < m) IC_decode(br, C, L, m);
        if (m < H) IC_decode(br, C, m, H);
        return;
    }

    uint32_t range = (uint32_t)(C[H] - C[L] + 1);
    int g = ceilLog2(range);

    uint32_t delta = (g == 0) ? 0u : br.readBits(g);
    C[m] = C[L] + (int32_t)delta;

    if (L < m) IC_decode(br, C, L, m);
    if (m < H) IC_decode(br, C, m, H);
}

static std::vector<uint8_t> image2DToBytes(const std::vector<std::vector<int32_t>>& img) {
    int h = (int)img.size();
    int w = h ? (int)img[0].size() : 0;

    std::vector<uint8_t> out((size_t)h * (size_t)w);
    for (int y = 0; y < h; ++y) {
        for (int x = 0; x < w; ++x) {
            int v = img[y][x];
            if (v < 0) v = 0;
            if (v > 255) v = 255;
            out[(size_t)y * (size_t)w + (size_t)x] = (uint8_t)v;
        }
    }
    return out;
}

static std::vector<uint8_t> decompress_to_bytes(const std::vector<uint8_t>& compressed) {
    BitReaderMem br(compressed.data(), compressed.size());
    Header h = readHeader(br);

    if (h.height == 0 || h.n < 2 || (h.n % h.height) != 0) {
        throw std::runtime_error("Invalid header");
    }

    int width = (int)(h.n / h.height);

    std::vector<int32_t> C(h.n, 0);
    C[0] = h.c0;
    C[h.n - 1] = h.cLast;

    IC_decode(br, C, 0, (int)h.n - 1);

    std::vector<int32_t> N;
    N.reserve(h.n);
    N.push_back(C[0]);
    for (uint32_t i = 1; i < h.n; ++i) {
        N.push_back(C[i] - C[i - 1]);
    }

    std::vector<int32_t> E;
    E.reserve(h.n);
    E.push_back(N[0]);
    for (uint32_t i = 1; i < h.n; ++i) {
        if ((N[i] & 1) == 0) E.push_back(N[i] / 2);
        else E.push_back(-(N[i] + 1) / 2);
    }

    auto img2d = predictInverse(E, (int)h.height, width);
    return image2DToBytes(img2d);
}




static int clamp255(int v) {
    if (v < 0) return 0;
    if (v > 255) return 255;
    return v;
}


int main(int argc, char** argv) {

    #ifdef _WIN32
    _setmode(_fileno(stdin), _O_BINARY);
    _setmode(_fileno(stdout), _O_BINARY);
    #endif


    if (argc < 2) {
        std::cerr << "Usage:\n"
                  << "  flocic --compress <width> <height>   (reads raw grayscale from stdin, writes compressed to stdout)\n"
                  << "  flocic --decompress                  (later)\n";
        return 2;
    }

    std::string mode = argv[1];

    if (mode == "--compress") {
        if (argc != 4) {
            std::cerr << "Usage: flocic --compress <width> <height>\n";
            return 2;
        }

        int width  = std::stoi(argv[2]);
        int height = std::stoi(argv[3]);
        if (width <= 0 || height <= 0) {
            std::cerr << "Invalid width/height\n";
            return 2;
        }

        size_t need = static_cast<size_t>(width) * static_cast<size_t>(height);
        std::vector<uint8_t> grayBytes;

        if (!readExactStdin(grayBytes, need)) {
            std::cerr << "Failed to read " << need << " bytes from stdin\n";
            return 1;
        }

        auto img2d = bytesToImage2D(grayBytes, width, height);
        auto compressed = compress_to_bytes(img2d, height, width);

        writeAllStdout(compressed);
        std::cout.flush();
        return 0;
    }

    if (mode == "--decompress") {
        try {
            auto compressed = readAllStdin();
            if (compressed.size() < 14) {
                std::cerr << "Input too small to contain header\n";
                return 1;
            }

            auto raw = decompress_to_bytes(compressed);

            writeAllStdout(raw);
            std::cout.flush();
            return 0;
        } catch (const std::exception& e) {
            std::cerr << "Decompress failed: " << e.what() << "\n";
            return 1;
        }
    }


    std::cerr << "Unknown mode: " << mode << "\n";
    return 2;
}
