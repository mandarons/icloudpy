from icloudpy import ICloudPyService
from icloudpy.services.photos import PhotosService

api = ICloudPyService(apple_id='jakub@tymejczyk.pl')


def print_albums_recursive(album, indent = 1):
    print('{}{}'.format('\t' * indent, album))
    if indent > 1:
        return
    for _, v in album.subalbums.items():
        print_albums_recursive(v, indent + 1)

for album in api.photos.albums:
    print(album)
    # if album not in PhotosService.SMART_FOLDERS:
    #     for photo in api.photos.albums[album].photos:
    #         print(photo)
    for _, v in api.photos.albums[album].subalbums.items():
        print_albums_recursive(v)
