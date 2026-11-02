from datetime import date, datetime
from sqlalchemy import (
    BigInteger,
    Boolean,
    Float,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    Date,
    DateTime,
    ForeignKey,
    UniqueConstraint,
)
from sqlalchemy import text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from database.db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)  # Telegram Chat ID
    phone: Mapped[str] = mapped_column(String(20), nullable=False)
    full_name: Mapped[str] = mapped_column(String(150), nullable=False)
    birth_date: Mapped[date] = mapped_column(Date, nullable=False)

    # Quyidagilar botning o'ziga kerak emas — ular olimpiadaga yozilishda
    # so'raladi va olympiad_results ga yoziladi. Ustunlar saqlab qolindi:
    # eski foydalanuvchilarning ma'lumoti shu yerda turibdi va yo'qolmasligi kerak.
    school: Mapped[str] = mapped_column(String(150), nullable=True)
    grade: Mapped[int] = mapped_column(Integer, nullable=True)
    teacher_name: Mapped[str] = mapped_column(String(150), nullable=True)
    registered_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ChatMenuButton(Base):
    """Chatga oxirgi marta berilgan "Open App" manzili (DECISIONS.md #42).

    Bot ishga tushganda manzil o'zgargan bo'lsa tugma shu chatga qayta
    yuboriladi (utils/platform.py -> sync_menu_buttons) — Telegram buni
    ilovaga darhol yetkazadi, aks holda ilova eski manzilni keshda saqlab,
    ishlamay qolgan sahifani ochib yuradi.

    `users` ga FK emas ataylab: xodimlar (superadmin, admin, ...) ko'pincha
    ro'yxatdan o'tmaydi, lekin "Open App" ni aynan ular ko'p ishlatadi.
    `url` bo'sh — tugma olib tashlangan (PLATFORM_URL o'chirilgan).
    """

    __tablename__ = "chat_menu_buttons"

    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    url: Mapped[str] = mapped_column(String(255), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Child(Base):
    """Foydalanuvchining farzandi — olimpiadaga shu yozuv orqali yoziladi.

    Ota-ona bir marta qo'shadi (familiya, ism, tug'ilgan sana, maktab, sinf),
    keyin har olimpiadada faqat o'qituvchi so'raladi. Bitta akkauntda bir
    nechta farzand bo'lishi mumkin (docs/DECISIONS.md #41).

    SINF O'ZI OSHADI: kiritilgan sinf `grade_year` (o'sha paytdagi o'quv yili
    boshlangan yil) bilan birga saqlanadi, joriy sinf esa
    `utils/utility.py -> current_grade` da hisoblanadi — ota-ona har yili
    qo'lda yangilab o'tirmaydi.

    O'chirilgan farzand `archived_at` bilan belgilanadi, qator o'chirilmaydi:
    uning olimpiada natijalari (OlympiadResult) tarix bo'lib qoladi.
    """

    __tablename__ = "children"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    first_name: Mapped[str] = mapped_column(String(150), nullable=False)
    last_name: Mapped[str] = mapped_column(String(150), nullable=False)
    birth_date: Mapped[date] = mapped_column(Date, nullable=False)
    school: Mapped[str] = mapped_column(String(150), nullable=True)
    grade: Mapped[int] = mapped_column(Integer, nullable=False)
    grade_year: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    archived_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)


class Admin(Base):
    __tablename__ = "admins"

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True
    )  # Telegram Chat ID of Admin
    role: Mapped[str] = mapped_column(
        String(20), default="admin"
    )  # 'superadmin' | 'admin' | 'teacher' | 'smm_manager'
    username: Mapped[str] = mapped_column(String(100), nullable=True)
    added_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Olympiad(Base):
    """Barcha olimpiadalar shu jadvalda saqlanadi (nomi va sanasi)."""

    __tablename__ = "olympiads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    # Ruxsatnoma ticket_no ichiga tushadigan qisqa kod (masalan "MATH").
    # Nomdan avtomatik hosil qilinadi (qarang: utils/utility.py ->
    # slugify_olympiad_code) — admin alohida kiritmaydi. Bir marta
    # hisoblangan ticket_no ichida qotib qoladi, shuning uchun bu yerda
    # keyinchalik o'zgarsa ham eski ruxsatnomalar buzilmaydi.
    code: Mapped[str] = mapped_column(String(10), nullable=True)
    exam_date: Mapped[date] = mapped_column(Date, nullable=True)
    # Faqat "faol" (is_active=True) olimpiadalar userga ro'yxatdan o'tish uchun ko'rsatiladi
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationships
    results: Mapped[list["OlympiadResult"]] = relationship(
        back_populates="olympiad", cascade="all, delete-orphan"
    )
    grades: Mapped[list["OlympiadGrade"]] = relationship(
        back_populates="olympiad",
        cascade="all, delete-orphan",
        order_by="OlympiadGrade.grade",
    )
    answer_sheet: Mapped["AnswerSheet"] = relationship(
        back_populates="olympiad", cascade="all, delete-orphan", uselist=False
    )
    time_slots: Mapped[list["OlympiadTimeSlot"]] = relationship(
        back_populates="olympiad",
        cascade="all, delete-orphan",
        order_by="OlympiadTimeSlot.position",
    )
    rooms: Mapped[list["OlympiadRoom"]] = relationship(
        back_populates="olympiad",
        cascade="all, delete-orphan",
        order_by="OlympiadRoom.room_number",
    )


class OlympiadGrade(Base):
    """Olimpiada qaysi sinflar uchun ekani.

    Sinflar vergulli satr sifatida emas, alohida qatorlar sifatida
    saqlanadi — shunda sinf bo'yicha filtr, reyting va eksport
    to'g'ridan-to'g'ri SQL darajasida ishlaydi.
    """

    __tablename__ = "olympiad_grades"
    __table_args__ = (
        UniqueConstraint("olympiad_id", "grade", name="uq_olympiad_grade"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    olympiad_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("olympiads.id", ondelete="CASCADE"), nullable=False
    )
    grade: Mapped[int] = mapped_column(Integer, nullable=False)

    olympiad: Mapped["Olympiad"] = relationship(back_populates="grades")


class OlympiadTimeSlot(Base):
    """Ishtirokchini qabul qilishda (reception check-in) tanlanadigan vaqt
    oralig'laridan biri (masalan "8:00 - 9:30"). Bir marta (sozlashda)
    kiritiladi, keyin qayta sozlanguncha o'zgarmaydi. Test/AnswerSheet
    tizimiga aloqasi yo'q — faqat xona/vaqt taqsimoti uchun.
    """

    __tablename__ = "olympiad_time_slots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    olympiad_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("olympiads.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)  # ko'rsatish tartibi
    label: Mapped[str] = mapped_column(String(50), nullable=False)

    olympiad: Mapped["Olympiad"] = relationship(back_populates="time_slots")


class OlympiadRoom(Base):
    """Ishtirokchini qabul qilishda tanlanadigan xonalardan biri.

    Sig'im HAR BIR VAQT VARIANTI uchun ALOHIDA hisoblanadi (bir xona turli
    vaqtlarda turli guruhlarni qabul qilishi mumkin) — bu yerdagi `capacity`
    xonaning BITTA vaqt oralig'idagi eng ko'p sig'imi, umumiy kun bo'yi
    emas (qarang: handlers/admin.py -> checkin_show_rooms, joriy sondan
    OlympiadResult.room_id + time_slot_id juftligi bo'yicha hisoblanadi).
    """

    __tablename__ = "olympiad_rooms"
    __table_args__ = (
        UniqueConstraint("olympiad_id", "room_number", name="uq_olympiad_room_number"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    olympiad_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("olympiads.id", ondelete="CASCADE"), nullable=False
    )
    room_number: Mapped[int] = mapped_column(Integer, nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False)

    olympiad: Mapped["Olympiad"] = relationship(back_populates="rooms")


class OlympiadResult(Base):
    """Har bir olimpiada ishtirokchisining natijasi.

    Har bir olimpiada uchun "alohida jadval" o'rniga bitta umumiy jadval
    ishlatiladi (olympiad_id orqali ajratiladi) — bu SQLAlchemy bilan
    xavfsiz va barqaror ishlaydi, lekin natija: har bir olimpiadaning
    ishtirokchilari va ballari alohida-alohida ko'rinadi.

    Ro'yxatdan o'tganda score/place hali NULL (bo'sh) bo'ladi — natija
    tekshirilgandan keyingina to'ldiriladi.
    """

    __tablename__ = "olympiad_results"
    # Bitta akkaunt bir olimpiadaga bir NECHTA farzandini yozdira oladi
    # (DECISIONS.md #41), shuning uchun eski (olympiad_id, user_id)
    # yagonaligi ikkiga bo'lindi:
    #   * farzand nomidan yozilgan qatorlar — har farzand bir marta;
    #   * eski, farzandsiz (child_id IS NULL) qatorlar — akkaunt bir marta.
    # Ikkalasi ham QISMAN (partial) indeks: to'liq UNIQUE bo'lsa NULL
    # child_id'li qatorlar bir-birini cheklamas edi.
    __table_args__ = (
        Index(
            "uq_olympiad_child",
            "olympiad_id",
            "child_id",
            unique=True,
            postgresql_where=text("child_id IS NOT NULL"),
        ),
        Index(
            "uq_olympiad_user_self",
            "olympiad_id",
            "user_id",
            unique=True,
            postgresql_where=text("child_id IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    olympiad_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("olympiads.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # Qaysi farzand nomidan yozilgan. Eski (farzandlar bo'limi paydo
    # bo'lishidan oldingi) yozuvlarda bo'sh — o'sha qatorlar akkaunt egasining
    # o'zi kiritgan ma'lumotlari bilan qolaveradi. Farzand ro'yxatdan
    # o'chirilsa (arxivlansa) natija yo'qolmaydi: qator o'chirilmaydi.
    child_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("children.id", ondelete="SET NULL"), nullable=True
    )
    full_name: Mapped[str] = mapped_column(String(150), nullable=True)

    # Familiya/ism alohida-alohida (ruxsatnomada ikkita alohida katta
    # shriftli maydon sifatida ko'rsatiladi). Eski yozuvlarda bular bo'sh —
    # o'sha holatda full_name'dan taxminiy ajratiladi (qarang:
    # utils/utility.py -> split_full_name). Yangi yozishda ikkalasi ham
    # to'ldiriladi, full_name ular birlashmasidan hosil qilinadi.
    first_name: Mapped[str] = mapped_column(String(150), nullable=True)
    last_name: Mapped[str] = mapped_column(String(150), nullable=True)

    # Ishtirokchining tug'ilgan sanasi (javob varag'ida ko'rsatiladi).
    # users.birth_date'dan FARQLI: bu yerdagi ishtirokchi Telegram
    # akkaunt egasidan boshqa odam bo'lishi mumkin (ota-ona farzandini
    # ro'yxatdan o'tkazgani kabi) — shuning uchun alohida so'raladi va
    # saqlanadi. Eski (bu maydon qo'shilishidan oldingi) yozuvlarda bo'sh —
    # o'sha holatda javob varag'i xizmati users.birth_date'ga qaytadi.
    birth_date: Mapped[date] = mapped_column(Date, nullable=True)

    # Ruxsatnoma ID'si. Bir marta (ro'yxatdan o'tishda) beriladi va hech
    # qachon o'zgarmaydi — QR va matn ko'rinishidagi ID shundan yasaladi.
    # QR kodning o'zi bazada saqlanmaydi, faqat shu qiymatdan qayta
    # hisoblanadi (qarang: utils/qr_payload.py, services/ticket_service.py).
    ticket_no: Mapped[str] = mapped_column(String(40), nullable=True)

    # Olimpiadaga yozilishda so'raladigan ma'lumotlar. Har olimpiadada
    # o'zgarishi mumkin (sinf oshadi, maktab almashadi), shuning uchun
    # foydalanuvchi profilida emas, aynan shu yozuvda saqlanadi.
    school: Mapped[str] = mapped_column(String(150), nullable=True)
    grade: Mapped[int] = mapped_column(Integer, nullable=True)
    teacher_name: Mapped[str] = mapped_column(String(150), nullable=True)

    # Ro'yxatdan o'tgandan keyin natija tekshirilmaguncha bular bo'sh (NULL) turadi
    # Ball butun son bo'lmasligi mumkin (masalan 71.2), shuning uchun Float.
    score: Mapped[float] = mapped_column(Float, nullable=True)
    percentage: Mapped[float] = mapped_column(Float, nullable=True)
    place: Mapped[int] = mapped_column(Integer, nullable=True)

    # Fan bo'yicha taqsimot (matn ko'rinishidagi natija va sertifikat uchun).
    # score = math_correct + english_correct bo'lishi shart emas — score asosiy
    # ko'rsatkich, bular esa qo'shimcha tafsilot sifatida saqlanadi.
    math_correct: Mapped[int] = mapped_column(Integer, nullable=True)
    math_total: Mapped[int] = mapped_column(Integer, nullable=True)
    english_correct: Mapped[int] = mapped_column(Integer, nullable=True)
    english_total: Mapped[int] = mapped_column(Integer, nullable=True)

    # Fan ichidagi savol-oraliqlari bo'yicha to'liq tafsilot (JSON matn sifatida).
    # Excel'da bir fan bir nechta ball-oralig'iga bo'lingan bo'lishi mumkin
    # (masalan 1-12-savollar va 13-30-savollar alohida ball beradi) — bu ustun
    # o'sha tafsilotni yo'qotmasdan saqlaydi. math_correct/math_total esa shu
    # oraliqlarning yig'indisi bo'lib qolaveradi (eski kod ular bilan ishlayveradi).
    # Tafsilot yo'q (eski yozuv yoki oddiy formatdagi fayl) bo'lsa — NULL.
    detail: Mapped[str] = mapped_column(Text, nullable=True)

    registered_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    checked_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)

    # Qabul qilish (reception check-in) bosqichi: ruxsatnoma bilan Smart
    # Academyga kelib, vaqt/xona belgilanganda to'ldiriladi (qarang:
    # handlers/admin.py -> _checkin_with_photo, DECISIONS.md #26, #39). DIQQAT:
    # checked_at bilan ALOQASI YO'Q — checked_at natija TEKSHIRILGAN vaqt,
    # attended_at esa ishtirokchi FIZIK QABUL QILINGAN vaqt (butunlay boshqa
    # narsa). FK EMAS ataylab: sozlama qayta o'zgartirilib eski xona/vaqt
    # o'chirilganda, shu ustunlar application darajasida (checkin_process
    # ichida, DB cascade orqali emas) aniq NULL qilinadi — DECISIONS.md #1
    # dagi "o'chirish emas, aniq boshqarish" falsafasiga mos.
    time_slot_id: Mapped[int] = mapped_column(Integer, nullable=True)
    room_id: Mapped[int] = mapped_column(Integer, nullable=True)
    # To'ldirilgan bo'lsa — "Ishtirokchi" (qabul qilingan). Bo'sh bo'lsa —
    # faqat "Ro'yxatdan o'tgan". Javob varag'i endi FAQAT shu maydon
    # to'ldirilgan qatorlar uchun generatsiya qilinadi.
    attended_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    # Qabul qilishda yuklangan ishtirokchi rasmi — faqat Telegram file_id,
    # rasmning o'zi serverda saqlanmaydi (DECISIONS.md #8, #39). Kirish
    # ruxsatnomasiga qo'yiladi; qayta qabulda "avvalgi rasm bilan davom
    # etish" uchun ham kerak.
    photo_file_id: Mapped[str] = mapped_column(String(255), nullable=True)

    # Relationships
    olympiad: Mapped["Olympiad"] = relationship(back_populates="results")
    user: Mapped["User"] = relationship()


class OnlineTest(Base):
    """Botning o'zida ishlanadigan test: javob kaliti (+ ixtiyoriy rasm).

    Savollar botda TARQATILMAYDI — ular kanaldagi e'londa turadi, bot esa
    faqat javobni tekshiradi (DECISIONS.md #46). `image_file_id` shuning
    uchun BO'SH bo'lishi mumkin: berilsa, o'quvchi test raqamini kiritganda
    ko'radigan muqova (reklama) rasmi bo'ladi. Eski testlarda bu ustunda
    savollar rasmi turibdi va avvalgidek yuboriladi.

    Rasm serverda saqlanmaydi — Telegram bergan file_id saqlanadi va
    o'quvchiga o'sha id bilan qayta yuboriladi. Shu tufayli disk ham,
    yuklab olish trafigi ham sarflanmaydi.
    """

    __tablename__ = "online_tests"

    # Bu raqamni admin o'zi tanlaydi — o'quvchi shuni botga kiritadi
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    title: Mapped[str] = mapped_column(String(200), nullable=True)
    # Ixtiyoriy muqova rasmi (bo'sh bo'lishi mumkin) — yuqoridagi izohga qarang.
    image_file_id: Mapped[str] = mapped_column(String(255), nullable=True)
    # "photo" yoki "document". Telegram rasmlarni siqadi va mayda matn
    # o'qilmay qolishi mumkin — shuning uchun admin siqilmagan fayl ham
    # yuborishi mumkin, o'quvchiga aynan shu ko'rinishda qaytariladi.
    file_type: Mapped[str] = mapped_column(String(20), nullable=False, server_default="photo")
    answers: Mapped[str] = mapped_column(Text, nullable=False)  # "A,B,C,D"
    created_by: Mapped[int] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Test "o'chirilganda" yozuv qolaveradi — o'quvchilarning natijalari
    # yo'qolmasligi uchun (Test modeli bilan bir xil yondashuv).
    archived: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    results: Mapped[list["OnlineTestResult"]] = relationship(
        back_populates="test", cascade="all, delete-orphan"
    )


class OnlineTestResult(Base):
    """O'quvchining online testdagi natijasi.

    Bir o'quvchi bir testni faqat bir marta ishlaydi — buni
    UniqueConstraint ta'minlaydi (imtihon tartibi).
    """

    __tablename__ = "online_test_results"
    __table_args__ = (
        UniqueConstraint("online_test_id", "user_id", name="uq_online_test_user"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    online_test_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("online_tests.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    given_answers: Mapped[str] = mapped_column(Text, nullable=False)
    correct: Mapped[int] = mapped_column(Integer, nullable=False)
    total: Mapped[int] = mapped_column(Integer, nullable=False)
    checked_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    test: Mapped["OnlineTest"] = relationship(back_populates="results")
    user: Mapped["User"] = relationship()


class AnswerSheet(Base):
    """Bitta olimpiadaning javob varag'i konfiguratsiyasi (necha fan,
    fanlar tartibi).

    QR-asosli (ticket_no orqali) javob varag'i.
    Har olimpiadada faqat bitta bo'ladi (bir marta sozlanadi, qayta
    sozlansa eski fanlar o'chirilib yangisi yoziladi).
    """

    __tablename__ = "answer_sheets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    olympiad_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("olympiads.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    # Oldindan chizib qo'yilgan BO'SH javob varag'i (bitta A4 sahifa PDF):
    # sarlavha, doiralar to'ri, ramkalar — hammasi bor, faqat ishtirokchi
    # ma'lumotlari bo'sh. Fanlar sozlanganda BIR MARTA hisoblanadi
    # (handlers/admin.py -> as_save). Eksportda har o'quvchi uchun shu sahifa
    # nusxalanib, ustiga ism/familiya/sana/sinf va QR "shtamplanadi"
    # (qarang: services/answer_sheet_service.py, DECISIONS.md #27).
    blank_pdf: Mapped[bytes] = mapped_column(LargeBinary, nullable=True)
    # Bo'sh shablondagi maydon koordinatalari (JSON) — shtamplashda qayerga
    # yozishni shu belgilaydi. blank_pdf bilan BIRGA yangilanadi: bittasi
    # eskirsa matn noto'g'ri joyga tushadi, shuning uchun doim juft holda
    # saqlanadi.
    field_boxes: Mapped[str] = mapped_column(Text, nullable=True)
    # Har bir javob doirasining markazi (JSON) — avtomatik tekshirish (OMR)
    # uchun. Tekshiruvchi doiralarni rasmdan qidirmaydi, shu ma'lum
    # joylardan o'qiydi (qarang: services/answer_sheet_service.py ->
    # extract_bubble_boxes, DECISIONS.md #29). blank_pdf bilan BIRGA
    # yangilanadi — varaq qayta chizilsa koordinatalar ham o'zgaradi.
    bubble_boxes: Mapped[str] = mapped_column(Text, nullable=True)

    olympiad: Mapped["Olympiad"] = relationship(back_populates="answer_sheet")
    subjects: Mapped[list["AnswerSheetSubject"]] = relationship(
        back_populates="answer_sheet",
        cascade="all, delete-orphan",
        order_by="AnswerSheetSubject.position",
    )


class AnswerSheetSubject(Base):
    """Javob varag'idagi bitta fan bloki (masalan Matematika, 30 savol, ABCDE).

    Fanlar vergulli satr emas, alohida qatorlar sifatida saqlanadi —
    OlympiadGrade bilan bir xil mantiq (qarang: DECISIONS.md #13).
    """

    __tablename__ = "answer_sheet_subjects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    answer_sheet_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("answer_sheets.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)  # chop etish tartibi: 1, 2, 3
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    question_count: Mapped[int] = mapped_column(Integer, nullable=False)
    choice_count: Mapped[int] = mapped_column(Integer, nullable=False)  # 4 (ABCD) yoki 5 (ABCDE)
    # To'g'ri javoblar kaliti — "A,B,C,D" ko'rinishida (Test/OnlineTest
    # bilan bir xil format, qarang: handlers/admin.py -> normalize_answers).
    # Admin QO'LDA kiritadi. Bo'sh bo'lsa varaqni avtomatik tekshirib
    # bo'lmaydi (qarang: DECISIONS.md #31).
    answer_key: Mapped[str] = mapped_column(Text, nullable=True)
    # Baholash mezoni (JSON) — `Test.math_rubric` bilan BIR XIL formatda,
    # shuning uchun `utils/utility.py -> apply_rubric` o'zgarishsiz
    # ishlatiladi. Bo'sh bo'lsa: 1 to'g'ri javob = 1 ball
    # (qarang: DECISIONS.md #33).
    rubric: Mapped[str] = mapped_column(Text, nullable=True)

    answer_sheet: Mapped["AnswerSheet"] = relationship(back_populates="subjects")


# ============================================================================
# OLIMPIADADAN TASHQARI javob varag'i (oddiy testlar uchun)
#
# Olimpiada javob varag'i (`AnswerSheet`) bilan BIR XIL texnologiya
# ishlatiladi (ArUco markerlar, QR, doira koordinatalari — qarang:
# services/answer_sheet_service.py), lekin u `Olympiad`ga qattiq
# bog'langan. Bu yerdagi varaq esa mustaqil: nomi bilan saqlanadi va
# ishtirokchilari Excel orqali kiritiladi (yoki umuman bo'lmaydi).
# Qarang: DECISIONS.md #34.
# ============================================================================


class TestSheet(Base):
    """Mustaqil javob varag'i (olimpiadaga bog'liq emas)."""

    __tablename__ = "test_sheets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Admin bergan nom — tekshirishda shu ro'yxatdan tanlanadi.
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    # True — ishtirokchilar Excel orqali kiritilgan va varaqlarda ularning
    # ma'lumoti bosilgan. False — bitta BO'SH varaq (maydonlar qo'lda
    # to'ldiriladi, QR o'rni faqat belgilab qo'yilgan).
    with_participants: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    created_by: Mapped[int] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Oldindan chizilgan bo'sh shablon va uning koordinatalari —
    # AnswerSheet'dagi bilan bir xil ma'no (DECISIONS.md #27, #29).
    blank_pdf: Mapped[bytes] = mapped_column(LargeBinary, nullable=True)
    field_boxes: Mapped[str] = mapped_column(Text, nullable=True)
    bubble_boxes: Mapped[str] = mapped_column(Text, nullable=True)

    subjects: Mapped[list["TestSheetSubject"]] = relationship(
        back_populates="test_sheet",
        cascade="all, delete-orphan",
        order_by="TestSheetSubject.position",
    )
    participants: Mapped[list["TestSheetParticipant"]] = relationship(
        back_populates="test_sheet",
        cascade="all, delete-orphan",
        order_by="TestSheetParticipant.row_no",
    )


class TestSheetSubject(Base):
    """Mustaqil varaqdagi bitta fan bloki (AnswerSheetSubject bilan bir xil)."""

    __tablename__ = "test_sheet_subjects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    test_sheet_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("test_sheets.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    question_count: Mapped[int] = mapped_column(Integer, nullable=False)
    choice_count: Mapped[int] = mapped_column(Integer, nullable=False)
    answer_key: Mapped[str] = mapped_column(Text, nullable=True)
    rubric: Mapped[str] = mapped_column(Text, nullable=True)

    test_sheet: Mapped["TestSheet"] = relationship(back_populates="subjects")


class TestSheetParticipant(Base):
    """Varaqda qatnashgan odam va uning natijasi.

    `users` jadvaliga BOG'LANMAYDI — bu odamlar botdan ro'yxatdan
    o'tmagan bo'lishi mumkin, ular shunchaki qog'ozda test yozadi.

    Bitta varaq bir nechta GURUHGA chiqarilishi mumkin (DECISIONS.md #47):
    har guruh o'z qatorlarini oladi, shablon va javob kaliti esa bitta
    bo'lib qolaveradi — shuning uchun bir xil test uchun ikkinchi varaq
    yaratish shart emas.
    """

    __tablename__ = "test_sheet_participants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    test_sheet_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("test_sheets.id", ondelete="CASCADE"), nullable=False
    )
    row_no: Mapped[int] = mapped_column(Integer, nullable=False)  # Excel tartibi

    ism: Mapped[str] = mapped_column(String(150), nullable=True)
    familiya: Mapped[str] = mapped_column(String(150), nullable=True)
    birth_date: Mapped[date] = mapped_column(Date, nullable=True)
    sinf: Mapped[str] = mapped_column(String(50), nullable=True)

    # Qaysi guruh uchun chiqarilgan. Bo'sh — varaq yaratilganda Excel
    # orqali kiritilgan birinchi ro'yxat. `guruh` — ko'rsatish va Excel
    # uchun nom, `classroom_id` — platformadagi guruhning o'zi: nomi
    # o'zgarsa ham o'sha guruh ekani bilinadi va qatorlar takrorlanmaydi.
    guruh: Mapped[str] = mapped_column(String(150), nullable=True)
    classroom_id: Mapped[str] = mapped_column(String(40), nullable=True)

    # QR uchun ID — olimpiadadagi bilan bir xil formatda
    # (utils/qr_payload.py -> build_ticket_no).
    ticket_no: Mapped[str] = mapped_column(String(40), nullable=True)

    # Tekshiruv natijasi
    score: Mapped[float] = mapped_column(Float, nullable=True)
    percentage: Mapped[float] = mapped_column(Float, nullable=True)
    detail: Mapped[str] = mapped_column(Text, nullable=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)

    test_sheet: Mapped["TestSheet"] = relationship(back_populates="participants")
