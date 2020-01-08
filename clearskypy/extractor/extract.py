import xarray as xr
import numpy as np
import math
import scipy
import datetime
import sys
import os


def date_check(date, date_start, date_end):
    if date_start <= date <= date_end:
        return date
    else:
        return np.datetime64('NaT')


def extract_dataset(lats, lons, dataset_path, variables, datetime, interpolate=True):
    """
    extract variables from dataset

    :param lats: numpy.ndarray
    :param lons: numpy.ndarray
    :param dataset_path: string
    :param variables: list of string
    :param datetime: numpy.ndarray [m,n]  m: time number n:station number
    :param interpolate: bool

    :return var: list of numpy.ndarray


    lons and lats determine a site coordinate together. lons.length==lat.length

    datavecs need to increase monotonically.

    """
    lons_unique, lons_index = np.unique(lons, return_inverse=True)
    lats_unique, lats_index = np.unique(lats, return_inverse=True)

    if datetime == []:
        var = []
        return var

    try:
        dataset = xr.open_dataset(dataset_path).sel(lat=lats_unique, lon=lons_unique, method='nearest')[
            variables]  # ectract nearest stations point for given lats and lons

    except:
        print('The data set does not contain the specified variable')
        return -1

    datetime_for_interp = np.unique(datetime[~np.isnat(datetime)])

    datetime_for_station = []

    for index_station in range(len(lons)):
        datetime_temp = datetime[:, index_station]
        datetime_temp = datetime_temp[~np.isnat(datetime_temp)]
        datetime_for_station.append(datetime_temp)

    if dataset['time'].size > 1:
        if interpolate:
            dataset_interpolation = dataset.interp(time=datetime_for_interp)  # use datevecs to interpolate
        else:
            try:
                dataset_interpolation = dataset.sel(time=datetime_for_interp)
            except:
                print('can not find data match specified time coordinate, exit with code -2. Maybe you want to '
                      'interpolate.')
                return -2

    else:
        dataset_interpolation = dataset

    var = []
    for index_variables in variables:
        if interpolate:
            station_data = np.empty([len(datetime), len(lats)], dtype=float)
            for index_station in range(len(lons)):
                if datetime_for_station[index_station].size == 0:
                    station_data[:, index_station] = np.full([1, len(datetime)], np.nan)
                else:
                    station_data[:, index_station] = np.array([dataset_interpolation[index_variables].sel(
                        lat=lats[index_station], lon=lons[index_station], method='nearest').sel(
                        time=datetime_for_station[index_station]).data]).T[:, 0]

        else:
            station_data = np.empty([len(lons_unique), 1], dtype=float)  # for phis
            for index_station in range(len(lons)):
                station_data[index_station, :] = np.array([dataset_interpolation[index_variables].sel(
                    lat=lats[index_station], lon=lons[index_station], method='nearest').data])[:, 0]
        var.append(station_data)

    return var


def extract_dataset_list(lats, lons, dataset_path_list, variables, datearray, interpolate=True):
    """
    extract variables from dataset

    :param lats: numpy.ndarray
    :param lons: numpy.ndarray
    :param dataset_path_list: list of string
    :param variables: list of string
    :param datearray: np.ndarray of np.datetime64
    :param interpolate: bool

    :return var: list of numpy.ndarray

    lons and lats determine a site coordinate together. lons.length==lat.length

    datavecs need to increase monotonically.

    """
    '''
    var_list = []
    for dataset_path in dataset_path_list:
        var = extract_dataset(lats, lons, dataset_path, variables, datevecs, interpolate)
        var_list.append(var)
    return var_list
    '''
    halfhour = datetime.timedelta(minutes=30)
    var_list = []
    for index_dataset in range(len(dataset_path_list)):
        dataset = xr.open_dataset(dataset_path_list[index_dataset])
        dataset_time = np.array(dataset['time'], dtype='datetime64[s]').astype(datetime.datetime)
        dataset_starttime = dataset_time[0]

        dataset_endtime = dataset_time[-1]

        date_check_vec = np.vectorize(date_check)

        datevecs_for_dataset = date_check_vec(datearray, dataset_starttime - halfhour, dataset_endtime + halfhour)

        newvar = extract_dataset(lats, lons, dataset_path_list[index_dataset], variables, datevecs_for_dataset,
                                 interpolate)
        if newvar != []:
            var_list.append(newvar)
    var = var_list[0]

    for index_varlist in range(len(var_list) - 1):
        if var_list[index_varlist + 1] == []:
            continue
        else:
            for index_variable in range(len(variables)):
                var[index_variable] = np.vstack((var[index_variable], var_list[index_varlist + 1][index_variable]))

    return var


def extract_for_MERRA2(lats, lons, times, elev, datadir):
    """
    Extract data from the MERRA2 database.
    """
    datadirlist = [os.listdir(datadir)][0]
    dirlist = []
    asmlist = []
    for file in datadirlist:
        if 'index' in file:
            continue
        elif 'const_2d_asm' in file:
            asmlist.append(datadir + file)
        elif 'merra2' in file:
            dirlist.append(datadir + file)
    variables = ['TOTEXTTAU', 'TOTSCATAU', 'TOTANGSTR', 'ALBEDO', 'TO3', 'TQV', 'PS']
    [AOD_550, tot_aer_ext, tot_angst, albedo, ozone, water_vapour, pressure] = extract_dataset_list(lats, lons,
                                                                                                    dirlist, variables,
                                                                                                    times,
                                                                                                    interpolate=True)
    # Get the MERRA2 cell height
    [phis] = extract_dataset(lats, lons, asmlist[0], ['PHIS'], times, interpolate=False)
    # apply conversions from raw MERRA2 units to clear-sky model units
    water_vapour = water_vapour * 0.1
    ozone = ozone * 0.001
    # convert height into metres
    h = phis / 9.80665
    h0 = elev
    # perform scale height correction
    Ha = 2100
    scale_height = np.exp((h0 - h) / Ha)
    AOD_550 = AOD_550 * scale_height.T
    water_vapour = water_vapour * scale_height.T
    tot_angst[tot_angst < 0] = 0

    # As no NO2 data in MERRA2, set to default value of 0.0002
    nitrogen_dioxide = np.tile(np.linspace(0.0002, 0.0002, np.size(times, 0)).reshape([np.size(times, 0), 1]),
                               lats.size)
    return [tot_aer_ext, AOD_550, tot_angst, ozone, albedo, water_vapour, pressure, nitrogen_dioxide]
